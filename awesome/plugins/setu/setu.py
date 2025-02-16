import random
import re
import time
from os import getcwd
from typing import Union

import nonebot
import pixivpy3
from aiocqhttp import MessageSegment
from loguru import logger
from pixivpy3 import PixivError

from Services.pixiv_word_cloud import get_word_cloud_img
from Services.rate_limiter import UserLimitModifier
from Services.util.common_util import compile_forward_message
from Services.util.ctx_utility import get_group_id, get_user_id, get_nickname
from Services.util.download_helper import download_image
from Services.util.sauce_nao_helper import sauce_helper
from awesome.Constants import user_permission as perm, group_permission
from awesome.Constants.function_key import SETU, AI_SETU, TRIGGER_BLACKLIST_WORD, HIT_XP
from awesome.plugins.util.helper_util import anime_reverse_search_response, set_group_permission
from config import SUPER_USER, PIXIV_REFRESH_TOKEN
from qq_bot_core import setu_control, user_control_module, admin_group_control, cangku_api, global_rate_limiter

get_privilege = lambda x, y: user_control_module.get_user_privilege(x, y)
pixiv_api = pixivpy3.AppPixivAPI()

ban_count = 3

HIGH_FREQ_KEYWORDS = [
    'white hair', 'cat ears', 'pantyhose', 'black pantyhose',
    'white pantyhose', 'arknights', 'genshin impact', 'yuri',
    'lolita', 'underclothes', 'full body', 'choker', 'masterpiece',
    'skirt', 'smile', 'collarbone', 'nurse, nurse cap', 'thighhights',
    'looking at viewer', '2girl'
]


class SetuRequester:
    def __init__(
            self, ctx: dict, has_id: bool,
            pixiv_id: Union[str, int], xp_result: list,
            requester_qq: Union[str, int], request_search_qq: Union[str, int]
    ):
        self.nickname = get_nickname(ctx)
        self.group_id = get_group_id(ctx)
        self.pixiv_id = pixiv_id
        self.has_id = has_id
        self.xp_result = xp_result
        self.requester_qq = str(requester_qq)
        self.search_target_qq = str(request_search_qq)


@nonebot.on_command('设置P站', aliases={'设置p站', 'p站设置'}, only_to_me=False)
async def set_user_pixiv(session: nonebot.CommandSession):
    arg = session.current_arg
    if not arg:
        await session.finish('把你P站数字ID给我交了kora！')

    ctx = session.ctx.copy()
    user_id = get_user_id(ctx)
    nickname = get_nickname(ctx)

    try:
        arg = int(arg)
    except ValueError:
        await session.finish('要的数字ID谢谢~')

    if setu_control.set_user_pixiv(user_id, arg, nickname):
        await session.finish('已设置！')

    await session.finish('不得劲啊你这……')


@nonebot.on_command('色图数据', only_to_me=False)
async def get_setu_stat(session: nonebot.CommandSession):
    setu_stat = setu_control.get_setu_usage()
    ai_use_stat = setu_control.get_global_stat(AI_SETU)
    setu_high_freq_keyword = setu_control.get_high_freq_keyword()
    setu_high_freq_keyword_to_string = "\n".join(f"{x[0]}: {x[1]}次" for x in setu_high_freq_keyword)
    await session.finish(f'色图功能共被使用了{setu_stat}次（其中{ai_use_stat}次为AI生成的，'
                         f'占比{ai_use_stat / setu_stat * 100:.2f}%），'
                         f'被查最多的关键词前10名为：\n{setu_high_freq_keyword_to_string}')


@nonebot.on_command('查询本群xp', aliases={'查询本群XP', '本群XP'}, only_to_me=False)
async def fetch_group_xp(session: nonebot.CommandSession):
    ctx = session.ctx.copy()
    if 'group_id' not in ctx:
        return

    group_id = get_group_id(ctx)
    group_xp = setu_control.get_group_xp(group_id)

    if not group_xp:
        await session.finish('本群还无数据哦~')

    await session.finish(f'本群XP查询第一名为{group_xp[0][0]} -> {group_xp[0][1]}')


@nonebot.on_command('词频', only_to_me=False)
async def get_setu_stat(session: nonebot.CommandSession):
    arg = session.current_arg
    if not arg:
        await session.finish('查啥词啊喂！！')

    await session.finish(setu_control.get_keyword_usage_literal(arg))


@nonebot.on_command('设置色图禁用', only_to_me=False)
async def set_black_list_group(session: nonebot.CommandSession):
    ctx = session.ctx.copy()
    user_id = get_user_id(ctx)
    if not user_control_module.get_user_privilege(user_id, perm.ADMIN):
        await session.finish('无权限')

    message = session.current_arg
    if 'group_id' not in ctx:
        args = message.split()
        if len(args) != 2:
            await session.finish('参数错误，应为！设置色图禁用 群号 设置，或在本群内做出设置')

        group_id = args[0]
        if not str(group_id).isdigit():
            await session.finish('提供的参数非qq群号')

        message = args[1]

    else:
        group_id = get_group_id(ctx)

    setting = set_group_permission(message, group_id, group_permission.BANNED)
    await session.finish(f'Done! {setting}')


@nonebot.on_command('色图', aliases='来张色图', only_to_me=False)
async def pixiv_send(session: nonebot.CommandSession):
    ctx = session.ctx.copy()
    nickname = get_nickname(ctx)
    message_id, allow_r18, user_id, group_id = _get_info_for_setu(ctx)

    if group_id != -1 and not get_privilege(user_id, perm.OWNER):
        if admin_group_control.get_group_permission(group_id, group_permission.BANNED):
            await session.finish('管理员已设置禁止该群接收色图。如果确认这是错误的话，请联系bot制作者')

    # 限流5秒单用户只能请求一次。
    user_limit = UserLimitModifier(5.0, 1.0, True)
    rate_limiter_check = await global_rate_limiter.user_limit_check(SETU, user_id, user_limit)
    if isinstance(rate_limiter_check, str):
        await session.finish(f'[CQ:reply,id={message_id}]{rate_limiter_check}')

    monitored = False

    warn, sanity = _sanity_check(group_id, user_id)
    if warn:
        await session.finish(warn)

    if sanity <= 0:
        await session.finish('差不多得了嗷')

    if not admin_group_control.get_if_authed():
        pixiv_api.set_auth(
            access_token=admin_group_control.get_access_token(),
            refresh_token='iL51azZw7BWWJmGysAurE3qfOsOhGW-xOZP41FPhG-s'
        )
        admin_group_control.set_if_authed(True)

    key_word = str(session.get('key_word', prompt='请输入一个关键字进行查询')).lower()

    multiplier = setu_control.get_bad_word_penalty(key_word)
    do_multiply = True
    if multiplier > 0:
        if multiplier * 2 > 400:
            setu_control.set_user_data(user_id, TRIGGER_BLACKLIST_WORD, nickname)
            if setu_control.get_user_data_by_tag(user_id, TRIGGER_BLACKLIST_WORD) >= ban_count:
                user_control_module.set_user_privilege(user_id, 'BANNED', True)
                await session.send(f'用户{user_id}已被封停机器人使用权限')
                bot = nonebot.get_bot()
                await bot.send_private_msg(
                    user_id=SUPER_USER,
                    message=f'User {user_id} has been banned for triggering prtection. Keyword = {key_word}'
                )

            else:
                await session.send('我劝这位年轻人好自为之，管理好自己的XP，不要污染图池')
                bot = nonebot.get_bot()
                await bot.send_private_msg(
                    user_id=SUPER_USER,
                    message=f'User {user_id} triggered protection mechanism. Keyword = {key_word}'
                )

            return

    if key_word in setu_control.get_monitored_keywords():
        monitored = True
        if 'group_id' in ctx:
            setu_control.set_user_data(user_id, HIT_XP, nickname)
            setu_control.set_user_xp(user_id, key_word, nickname)

    elif '色图' in key_word:
        await session.finish(
            MessageSegment.image(
                f'file:///{getcwd()}/data/dl/others/QQ图片20191013212223.jpg'
            )
        )

    elif '屑bot' in key_word:
        await session.finish('你屑你🐴呢')

    json_result = {}

    try:
        if '最新' in key_word:
            json_result = pixiv_api.illust_ranking('week')
        else:
            json_result = pixiv_api.search_illust(
                word=key_word,
                sort="popular_desc"
            )

    except pixivpy3.PixivError:
        await session.finish('pixiv连接出错了！')

    except Exception as err:
        logger.warning(f'pixiv search error: {err}')
        await session.finish(f'发现未知错误')

    # 看一下access token是否过期
    if 'error' in json_result:
        if not set_function_auth():
            return

    if key_word.isdigit():
        illust = pixiv_api.illust_detail(key_word).illust
    else:
        if 'user=' in key_word:
            json_result, key_word = _get_image_data_from_username(key_word)
            if isinstance(json_result, str):
                await session.finish(json_result)

        else:
            json_result = pixiv_api.search_illust(word=key_word, sort="popular_desc")

        if not json_result.illusts or len(json_result.illusts) < 4:
            logger.warning(f"未找到图片, keyword = {key_word}")
            await session.send(f"{key_word}无搜索结果或图片过少……")
            return

        setu_control.track_keyword(key_word)
        illust = random.choice(json_result.illusts)

    is_work_r18 = illust.sanity_level == 6
    if not allow_r18:
        if is_work_r18 and not key_word.isdigit():
            # Try 10 times to find a SFW image.
            for i in range(10):
                illust = random.choice(json_result.illusts)
                is_work_r18 = illust.sanity_level == 6
                if not is_work_r18:
                    break
            else:
                await session.finish('太色了发不了（')

    elif not allow_r18 and key_word.isdigit():
        await session.finish('太色了发不了（')

    if not monitored:
        if is_work_r18:
            setu_control.drain_sanity(
                group_id=group_id,
                sanity=3 if not do_multiply else 2 * multiplier
            )
        else:
            setu_control.drain_sanity(
                group_id=group_id,
                sanity=1 if not do_multiply else 1 * multiplier
            )

    start_time = time.time()
    path = await _download_pixiv_image_helper(illust)

    bot = nonebot.get_bot()

    if not is_work_r18:
        message = f'[CQ:reply,id={message_id}]' \
                  f'Pixiv ID: {illust.id}\n' \
                  f'标题：{illust.title}\n' \
                  f'查询关键词：{key_word}\n' \
                  f'画师：{illust["user"]["name"]}\n' \
                  f'{MessageSegment.image(f"file:///{path}")}\n' \
                  f'Download Time: {(time.time() - start_time):.2f}s'

    # group_id = -1 when private session.
    elif is_work_r18 and (group_id == -1 or allow_r18):
        message = f'[CQ:reply,id={message_id}]' \
                  f'芜湖~好图来了ww\n' \
                  f'标题：{illust.title}\n' \
                  f'Pixiv ID: {illust.id}\n' \
                  f'关键词：{key_word}\n' \
                  f'画师：{illust["user"]["name"]}\n' \
                  f'[CQ:image,file=file:///{path}]\n' \
                  f'Download Time: {(time.time() - start_time):.2f}s'

    else:
        message = '图片发送失败！'

    await bot.send_group_forward_msg(
        group_id=group_id,
        messages=compile_forward_message(session.self_id, message)
    )

    logger.info("sent image on path: " + path)
    await _setu_data_collection(ctx, key_word, monitored, path, illust)


async def _setu_data_collection(ctx: dict, key_word: str, monitored: bool, path: str, illust=None):
    if 'group_id' in ctx:
        setu_control.set_group_data(get_group_id(ctx), SETU)

    nickname = get_nickname(ctx)

    user_id = get_user_id(ctx)
    setu_control.set_user_data(user_id, SETU, nickname)
    key_word_list = re.split(r'[\s\u3000,]+', key_word)
    for keyword in key_word_list:
        setu_control.set_user_xp(user_id, keyword, nickname)
        setu_control.set_group_xp(get_group_id(ctx), keyword)

    if illust is not None:
        tags = illust.tags
        tags = [x for x in list(tags) if x not in setu_control.blacklist_freq_keyword]
        if len(tags) > 5:
            tags = tags[:5]
        for tag in tags:
            setu_control.set_group_xp(get_group_id(ctx), tag['name'])
            setu_control.set_user_xp(user_id, tag['name'], nickname)

    if monitored and not get_privilege(user_id, perm.OWNER):
        bot = nonebot.get_bot()
        await bot.send_private_msg(
            user_id=SUPER_USER,
            message=f'图片来自：{nickname}\n'
                    f'查询关键词:{key_word}\n'
                    f'Pixiv ID: {illust.id}\n'
                    '关键字在监控中' + f'[CQ:image,file=file:///{path}]'
        )


def _sanity_check(group_id, user_id):
    if group_id in setu_control.get_sanity_dict():
        sanity = setu_control.get_sanity(group_id)
        return '', sanity

    elif group_id == -1 and not get_privilege(user_id, perm.WHITELIST):
        return '我主人还没有添加你到信任名单哦。请找BOT制作者要私聊使用权限~', -1

    else:
        sanity = setu_control.get_max_sanity()
        setu_control.set_sanity(group_id=group_id, sanity=setu_control.get_max_sanity())
        return '', sanity


def _validate_user_pixiv_id_exists_and_return_id(session, ctx):
    arg = session.current_arg

    if arg.isdigit():
        search_target_qq = arg
    elif re.match(r'.*?\[CQ:at,qq=(\d+)]', arg):
        search_target_qq = re.findall(r'.*?\[CQ:at,qq=(\d+)]', arg)[0]
    else:
        search_target_qq = get_user_id(ctx)

    search_target_qq = int(search_target_qq)
    pixiv_id = setu_control.get_user_pixiv(search_target_qq)

    return pixiv_id != -1, search_target_qq, pixiv_id


@nonebot.on_command('P站词云', only_to_me=False)
async def get_user_xp_wordcloud(session: nonebot.CommandSession):
    if not admin_group_control.get_if_authed():
        pixiv_api.auth(
            refresh_token=PIXIV_REFRESH_TOKEN
        )
        admin_group_control.set_if_authed(True)

    ctx = session.ctx.copy()
    group_id = get_group_id(ctx)

    has_id, search_target_qq, pixiv_id = _validate_user_pixiv_id_exists_and_return_id(session, ctx)
    if not has_id:
        await session.finish('无法生成词云，请设置P站ID，设置方法：!设置P站 P站数字ID')

    await session.send('少女祈祷中……生成词云可能会占用大概1分钟的时间……')
    try:
        cloud_img_path = await get_word_cloud_img(pixiv_api, pixiv_id)
    except PixivError:
        await session.finish('P站请求失败！请重新使用本指令！')
        return

    message_id = ctx['message_id']
    messages = compile_forward_message(session.self_id, f'[CQ:reply,id={message_id}]\n' +
                                       f'[CQ:image,file=file:///{cloud_img_path}]')

    bot = nonebot.get_bot()
    await bot.send_group_forward_msg(group_id=group_id, messages=messages)


@nonebot.on_command('看看XP', aliases={'看看xp'}, only_to_me=False)
async def get_user_xp_data_with_at(session: nonebot.CommandSession):
    ctx = session.ctx.copy()
    friendly_reminder = '\n你知道么~你可以使用你的p站uid丢人了（不是w\n' \
                        '使用方式：!设置P站 P站数字ID \n' \
                        '（进入自己的用户页面，你会看到url后面跟着一串数字）'

    group_id = get_group_id(ctx)
    if group_id != -1 and not get_privilege(get_user_id(ctx), perm.OWNER):
        if admin_group_control.get_group_permission(group_id, group_permission.BANNED):
            await session.finish('管理员已设置禁止该群接收色图。如果确认这是错误的话，请联系bot制作者')

    requester_qq = get_user_id(ctx)
    warn, sanity = _sanity_check(group_id, requester_qq)
    if warn:
        await session.finish(warn)

    if sanity <= 0:
        await session.finish('差不多得了嗷')

    message_id = ctx['message_id']

    has_id, search_target_qq, pixiv_id = _validate_user_pixiv_id_exists_and_return_id(session, ctx)
    xp_result = setu_control.get_user_xp(search_target_qq)
    if not has_id and xp_result == '暂无数据':
        await session.finish(
            f'[CQ:reply,id={message_id}]' + friendly_reminder
        )

    group_id = get_group_id(ctx)

    xp_information = SetuRequester(ctx, has_id, pixiv_id, xp_result, requester_qq, search_target_qq)
    result = await _get_xp_information(xp_information)
    setu_control.drain_sanity(group_id)
    final_message = f'[CQ:reply,id={message_id}]{result}\n{friendly_reminder if not has_id else ""}'
    messages = compile_forward_message(session.self_id, final_message)

    bot = nonebot.get_bot()
    await bot.send_group_forward_msg(group_id=group_id, messages=messages)


async def _get_xp_information(xp_information: SetuRequester) -> str:
    response = ''
    if xp_information.has_id:
        json_result = _get_user_bookmark_data(int(xp_information.pixiv_id))
    else:
        json_result = pixiv_api.search_illust(
            word=xp_information.xp_result[0],
            sort="popular_desc"
        )
    json_result = json_result.illusts
    if not json_result:
        return '不是吧~你P站都不收藏图的么（'

    illust = random.choice(json_result)
    start_time = time.time()
    path = await _download_pixiv_image_helper(illust)
    allow_r18 = xp_information.group_id != -1 \
                and admin_group_control.get_group_permission(xp_information.group_id, group_permission.ALLOW_R18)
    is_r18 = illust.sanity_level == 6
    iteration = 0

    if not allow_r18:
        while is_r18 and iteration < 10:
            if not is_r18:
                break

            illust = random.choice(json_result)
            is_r18 = illust.sanity_level == 6
            iteration += 1
        else:
            return '目前找不到好图呢~'

    nickname = xp_information.nickname

    if xp_information.group_id != -1:
        setu_control.set_group_data(xp_information.group_id, SETU)

    tags = illust['tags']

    for tag in tags:
        tag_name = tag['name']
        setu_control.set_user_xp(xp_information.search_target_qq, tag_name, nickname)
        setu_control.track_keyword(tag_name)
        setu_control.set_group_xp(xp_information.group_id, tag_name)

    response += f'标题：{illust.title}\n' \
                f'Pixiv ID： {illust.id}\n' \
                f'画师：{illust["user"]["name"]}\n' \
                f'[CQ:image,file=file:///{path}]\n' \
                f'Download Time: {(time.time() - start_time):.2f}s\n'

    response += f'TA最喜欢的关键词是{xp_information.xp_result[0]}，' \
                f'已经查询了{xp_information.xp_result[1]}次。' if not isinstance(xp_information.xp_result, str) else ''

    setu_control.set_user_data(xp_information.requester_qq, SETU, nickname)
    return response.strip()


def _get_user_bookmark_data(pixiv_id: int):
    if not admin_group_control.get_if_authed():
        pixiv_api.set_auth(
            access_token=admin_group_control.get_access_token(),
            refresh_token=PIXIV_REFRESH_TOKEN
        )
        admin_group_control.set_if_authed(True)

    json_result_list = []
    json_result = pixiv_api.user_bookmarks_illust(user_id=pixiv_id)

    # 看一下access token是否过期
    if 'error' in json_result:
        if not set_function_auth():
            return

        json_result = pixiv_api.user_bookmarks_illust(user_id=pixiv_id)

    json_result_list.append(json_result)
    random_loop_time = random.randint(1, 30)
    for _ in range(random_loop_time):
        next_qs = pixiv_api.parse_qs(json_result.next_url)
        if next_qs is None or 'max_bookmark_id' not in next_qs:
            break
        json_result = pixiv_api.user_bookmarks_illust(user_id=pixiv_id, max_bookmark_id=next_qs['max_bookmark_id'])
        json_result_list.append(json_result)

    return random.choice(json_result_list)


def _get_image_data_from_username(key_word: str) -> (str, str):
    key_word = re.findall(r'{user=(.*?)}', key_word)
    logger.info(f'Searching artist: {key_word}')
    if key_word:
        key_word = key_word[0]
        logger.info(f'Artist extracted: {key_word}')
    else:
        return '未找到该用户。', ''

    json_user = pixiv_api.search_user(word=key_word, sort="popular_desc")
    if json_user['user_previews']:
        user_id = json_user['user_previews'][0]['user']['id']
        json_result = pixiv_api.user_illusts(user_id)
        return json_result, key_word
    else:
        return f"{key_word}无搜索结果或图片过少……", ''


async def _download_pixiv_image_helper(illust):
    if illust['meta_single_page']:
        if 'original_image_url' in illust['meta_single_page']:
            image_url = illust.meta_single_page['original_image_url']
        else:
            image_url = illust.image_urls['medium']
    else:
        if 'meta_pages' in illust:
            image_url_list = illust.meta_pages
            illust = random.choice(image_url_list)

        image_urls = illust.image_urls
        image_url = image_urls['original'] if 'original' in image_urls else \
            image_urls['large'] if 'large' in image_urls else \
                image_urls['medium'] if 'medium' in image_urls else \
                    image_urls['square_medium']

    logger.info(f"{illust.title}: {image_url}, {illust.id}")
    path = f'{getcwd()}/data/pixivPic/'

    try:
        path = await download_image(image_url, path, headers={'Referer': 'https://app-api.pixiv.net/'})
    except Exception as err:
        logger.info(f'Download image error: {err}')

    logger.info("PATH = " + path)
    return path


@nonebot.on_command('搜图', only_to_me=False)
async def reverse_image_search(session: nonebot.CommandSession):
    args = session.current_arg_images
    if args:
        url = args[0]
        logger.info(f'URL extracted: {url}')
        try:
            response_data = await sauce_helper(url)
            if not response_data:
                response = f'图片无法辨别的说！'
            else:
                response = anime_reverse_search_response(response_data)

            await session.finish(response)
        except Exception as err:
            logger.warning(f'Error when reverse searching image data {err}')

        return
    else:
        await session.finish('¿')


def set_function_auth() -> bool:
    admin_group_control.set_if_authed(False)
    try:
        pixiv_api.auth(refresh_token=PIXIV_REFRESH_TOKEN)
        admin_group_control.set_if_authed(True)

    except pixivpy3.PixivError as err:
        logger.warning(err)
        return False

    return True


@nonebot.on_command('仓库搜索', only_to_me=False)
async def cangku_search(session: nonebot.CommandSession):
    key_word = str(session.get('key_word', prompt='请输入关键字进行查询')).lower()
    ctx = session.ctx.copy()
    if 'group_id' not in ctx:
        allow_r18 = True
    else:
        group_id = get_group_id(ctx)
        allow_r18 = admin_group_control.get_group_permission(group_id, group_permission.ALLOW_R18)

    user_id = get_user_id(ctx)
    user_id = str(user_id)

    search_result = cangku_api.get_search_string(
        key_word,
        user_id=user_id,
        is_r18=allow_r18
    )
    index = session.get(
        'index_name',
        prompt=search_result + '\n'
                               '请输入序号进行查询~'
    )
    search_by_index = cangku_api.get_info_by_index(user_id, index)
    dissect_to_string = cangku_api.anaylze_dissected_data(search_by_index)
    await session.finish(dissect_to_string)


@pixiv_send.args_parser
@cangku_search.args_parser
async def _(session: nonebot.CommandSession):
    stripped_arg = session.current_arg_text
    if session.is_first_run:
        if stripped_arg:
            session.state['key_word'] = stripped_arg
        return

    if not stripped_arg:
        session.pause('要查询的关键词不能为空')

    session.state[session.current_key] = stripped_arg


@set_black_list_group.args_parser
async def _set_group_property(session: nonebot.CommandSession):
    stripped_arg = session.current_arg_text
    if session.is_first_run:
        if stripped_arg:
            session.state['group_id'] = stripped_arg
        return

    if not stripped_arg:
        ctx = session.ctx.copy()
        if 'group_id' not in ctx:
            session.pause('qq组号不能为空')
        else:
            session.state['group_id'] = get_group_id(ctx)

    session.state[session.current_key] = stripped_arg


def _get_info_for_setu(ctx):
    message_id = ctx['message_id']

    group_id = get_group_id(ctx)
    allow_r18 = admin_group_control.get_group_permission(group_id, group_permission.ALLOW_R18)
    user_id = get_user_id(ctx)

    return message_id, allow_r18, user_id, group_id
