# -*- coding: utf-8 -*-#

from bridge.context import ContextType
from channel.chat_message import ChatMessage
from common.log import logger
from common.media_download import MAX_FILE_BYTES, MAX_IMAGE_BYTES, save_response
from common.tmp_dir import TmpDir


class WeChatMPMessage(ChatMessage):
    # Message types __init__ can parse; anything else raises NotImplementedError.
    # The callbacks gate on this rather than repeating the list, so the two
    # cannot drift -- a type added here becomes reachable without editing them.
    SUPPORTED_TYPES = ("text", "voice", "image")

    def __init__(self, msg, client=None):
        super().__init__(msg)
        self.msg_id = msg.id
        self.create_time = msg.time
        self.is_group = False

        if msg.type == "text":
            self.ctype = ContextType.TEXT
            self.content = msg.content
        elif msg.type == "voice":
            if msg.recognition == None:
                self.ctype = ContextType.VOICE
                self.content = TmpDir().path() + msg.media_id + "." + msg.format  # content直接存临时目录路径

                def download_voice():
                    # 如果响应状态码是200，则将响应内容写入本地文件
                    response = client.media.download(msg.media_id)
                    if response.status_code == 200:
                        try:
                            save_response(response, self.content, MAX_FILE_BYTES)
                        except Exception as e:
                            logger.error(f"[wechatmp] Failed to download voice file: {e}")
                    else:
                        logger.info(f"[wechatmp] Failed to download voice file, {response.content}")

                self._prepare_fn = download_voice
            else:
                self.ctype = ContextType.TEXT
                self.content = msg.recognition
        elif msg.type == "image":
            self.ctype = ContextType.IMAGE
            self.content = TmpDir().path() + msg.media_id + ".png"  # content直接存临时目录路径

            def download_image():
                # 如果响应状态码是200，则将响应内容写入本地文件
                response = client.media.download(msg.media_id)
                if response.status_code == 200:
                    try:
                        save_response(response, self.content, MAX_IMAGE_BYTES)
                    except Exception as e:
                        logger.error(f"[wechatmp] Failed to download image file: {e}")
                else:
                    logger.info(f"[wechatmp] Failed to download image file, {response.content}")

            self._prepare_fn = download_image
        else:
            raise NotImplementedError("Unsupported message type: Type:{} ".format(msg.type))

        self.from_user_id = msg.source
        self.to_user_id = msg.target
        self.other_user_id = msg.source
