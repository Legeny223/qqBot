import json
import os
from typing import Union

import requests
from aiocqhttp import MessageSegment

from qq_bot_core import admin_group_control

HHSHMEANING = 'meaning'
FURIGANAFUNCTION = 'furigana'
WIKIPEDIA = 'WIKIPEDIA'


def set_group_permission(message: str, group_id: Union[str, int], tag: str) -> bool:
    group_id = str(group_id)
    if '开' in message:
        admin_group_control.set_group_permission(group_id=group_id, tag=tag, stat=True)
        return True

    admin_group_control.set_group_permission(group_id=group_id, tag=tag, stat=False)
    return False


def download_image_to_path(response, path):
    url = response['url']
    image_response = requests.get(
        url,
        stream=True
    )
    image_response.raise_for_status()
    path = f'{path}/{response["filename"]}'
    if not os.path.exists(path):
        with open(path, 'wb') as file:
            file.write(image_response.content)

    return path


def get_downloaded_image_path(response: dict, path: str):
    path = download_image_to_path(response, path)
    resp = str(MessageSegment.image(f'file:///{path}'))
    return resp


class HhshCache:
    def __init__(self):
        self.meaning_dict = {}  # str : str
        self.furigana_dict = {}
        self.wikipedia_dict = {}

    def check_exist(self, query, function):
        if function == HHSHMEANING:
            return query in self.meaning_dict

        if function == FURIGANAFUNCTION:
            return query in self.furigana_dict

    @staticmethod
    def _check_and_delete_first_key(d: dict) -> None:
        if len(d) > 100:
            first_key = next(iter(d))
            del d[first_key]

    def store_result(
            self,
            query: str,
            meaning: str,
            function: (HHSHMEANING or FURIGANAFUNCTION or WIKIPEDIA)
    ):
        if function == HHSHMEANING:
            self._check_and_delete_first_key(self.meaning_dict)
            self.meaning_dict[query] = meaning

        elif function == FURIGANAFUNCTION:
            self._check_and_delete_first_key(self.furigana_dict)
            self.furigana_dict[query] = meaning

        elif function == WIKIPEDIA:
            self._check_and_delete_first_key(self.wikipedia_dict)
            self.wikipedia_dict[query] = meaning

    def get_result(self, query, function):
        def _get_result_if_exists(d: dict, q: str) -> str:
            return d[q] if q in d else ''

        if function == HHSHMEANING:
            return _get_result_if_exists(self.meaning_dict, query)

        if function == FURIGANAFUNCTION:
            return _get_result_if_exists(self.furigana_dict, query)

        if function == WIKIPEDIA:
            return _get_result_if_exists(self.wikipedia_dict, query)


def ark_helper(args: list) -> str:
    if len(args) < 2:
        return '用法有误\n' + '使用方法：！命令 干员名 星级（数字）'

    if not args[1].isdigit():
        return '使用方法有误，第二参数应为数字'

    return ''


def send_message_with_mini_program(title: str, content: list, image=None, action: list = None) -> str:
    data = {
        "app": "com.tencent.miniapp",
        "desc": "",
        "view": "notification",
        "ver": "1.0.0.11",
        "prompt": "[又有lsp在搜图]",
        "appID": "",
        "sourceName": "",
        "actionData": "",
        "actionData_A": "",
        "sourceUrl": "",
        "meta": {
            "notification": {
                "appInfo": {
                    "appName": "",
                    "appType": 4,
                    "appid": 1109659848,
                    "iconUrl": image if image is not None else ""
                },
                "data": content,
                "title": title,
                "button": action if action is not None else [],
                "emphasis_keyword": ""
            }
        },
        "text": "",
        "sourceAd": ""
    }

    result = json.dumps(data)
    result = result.replace('&', '&amp;').replace(',', '&#44;').replace('[', '&#91;').replace(']', '&#93;')
    return f'[CQ:json,data={result}]'


def anime_reverse_search_response(response_data: dict) -> str:
    if 'est_time' in response_data:
        response = f'{response_data["thumbnail"]}\n' \
                   f'相似度：{response_data["simlarity"]}\n' \
                   f'番名：{response_data["source"]}\n' \
                   f'番剧年份：{response_data["year"]}\n' \
                   f'集数：{response_data["part"]}\n' \
                   f'大概出现时间：{response_data["est_time"]}'
    else:
        if response_data['ext_url'] == '[数据删除]':
            response = f'{response_data["data"]}\n' \
                       f'相似度：{response_data["simlarity"]}\n' \
                       f'标题：{response_data["title"]}\n' \
                       f'画师：{response_data["author"]}\n'
        else:
            response = f'{response_data["data"]}\n' \
                       f'相似度：{response_data["simlarity"]}\n' \
                       f'标题：{response_data["title"]}\n' \
                       f'画师：{response_data["author"]}\n' \
                       f'Pixiv：{response_data["pixiv_id"]}\n'

    if 'simlarity' in response_data and float(response_data["simlarity"].replace('%', '')) < 70:
        response += '\n\n不过我不是太有信心哦~'

    return response


def send_as_xml_message(
        brief: str, title: str, summary: str,
        url: str = None, image: str = None,
        source: str = None
):
    message = f"""
    <?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
    <msg 
        serviceID="146" templateID="1" action="web" 
        brief="{brief}" sourceMsgId="0" url="{url if url is not None else 'https://www.example.com'}" 
        flag="0" adverSign="0" multiMsgFlag="0"
    >
        <item layout="2" advertiser_id="0" aid="0">
            <picture cover="{image if image is not None else ''}" />
            <title>{title}</title>
            <summary>{summary}</summary>
        </item>
        <source 
            name="{source if source is not None else '官方认证消息'}" 
            icon="https://qzs.qq.com/ac/qzone_v5/client/auth_icon.png" action="" appid="-1" 
        />
    </msg>
    """
    return f'[CQ:xml,data={message}]'
