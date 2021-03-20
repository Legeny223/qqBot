# 关于	

## 主要功能

* YouTube频道监控（可通知直播间设置以及开播）
* Twitter监控（可通知新推、转推、和回推）
* 多种娱乐功能（轮盘赌、明日方舟十连寻访模拟、嘴臭等）
* YouTube自动/手动下源
* 色图功能！（需要Pixiv账号）
* 搜图功能（支持使用“回复”并直接输入搜图来进行搜图，或者！搜图 [图片]（详见说明文档）
* 警报系统（在高网络延迟的情况下停用部分功能）
* 权限系统（想要什么群，什么用户使用什么功能均可进行自定义）

说明文档在[这里](https://github.com/remiliacn/Lingye-Bot)


# Config
建议进行以下设置：
```python3
from nonebot.default_config import *

NICKNAME = {}

consumer_key = '' # twitter API consumer key
consumer_secret = '' # twitter API consumer secret
access_token = '' # twitter API access token
access_secret = '' # twitter API access secret

sauce_nao_API_key = '' # Generate your API key from here: https://saucenao.com/user.php?page=search-api

user_name = '' # Pixiv login username
password = '' # Pixiv login password

downloader = 'forDownload.py'
path_export = ''                # OneDrive path for downloaded video.
path_temp = ''                  # Temp saving path for downloaded video.
ffmpeg_path = ''                # If ffmpeg is not in $path, here should be set.
share_link = ''                 # OneDrive share link.

SUPER_USER = 0 # Report will be sent to this qq.

itpk_key = '' # 茉莉机器人API key
itpk_secret = '' # 茉莉机器人API secret

HOST = '127.0.0.1'
PORT = 5700
```

在配置后可能会出现部分文件缺失的情况，请按需删除不需要的参数。（因为有些功能是为某些群的需求特供的，所以可能不适合大部分用户）

