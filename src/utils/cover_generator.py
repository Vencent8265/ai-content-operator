"""
AI 封面图生成器
─────────────
调用通义万相（DashScope）生成文章封面图。
"""

import base64
import logging
import os
from pathlib import Path
from datetime import datetime

import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

COVER_DIR = Path("data/covers")


class CoverGenerator:
    """
    封面图生成器。

    用法：
        gen = CoverGenerator()
        url = gen.generate("AI技术封面 科技蓝色风格")
        # 返回本地文件路径
    """

    DASHSCOPE_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis"

    def __init__(self):
        self.api_key = os.getenv("DASHSCOPE_API_KEY")
        if not self.api_key:
            logger.warning("DASHSCOPE_API_KEY 未设置，封面生成不可用")
        COVER_DIR.mkdir(parents=True, exist_ok=True)

    def generate(self, prompt: str, size: str = "1024*1024") -> str:
        """
        生成封面图。

        Args:
            prompt: 图片描述（中文）
            size: 尺寸

        Returns:
            本地文件路径，失败返回空字符串
        """
        if not self.api_key:
            return ""

        client = httpx.Client(timeout=60)

        try:
            resp = client.post(
                self.DASHSCOPE_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "X-DashScope-Async": "enable",
                },
                json={
                    "model": "wanx2.0-t2i-turbo",
                    "input": {
                        "prompt": prompt,
                        "negative_prompt": "低质量, 模糊, 文字, 水印",
                    },
                    "parameters": {
                        "size": size,
                        "n": 1,
                    },
                },
            )
            data = resp.json()

            if "output" not in data or "task_id" not in data.get("output", {}):
                logger.warning(f"封面生成失败: {data}")
                return ""

            task_id = data["output"]["task_id"]
            logger.info(f"封面任务: {task_id}")

            # 轮询等待结果
            import time
            for _ in range(20):
                time.sleep(3)
                status_resp = client.get(
                    f"https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                status = status_resp.json()
                task_status = status.get("output", {}).get("task_status", "")

                if task_status == "SUCCEEDED":
                    img_url = status["output"]["results"][0]["url"]
                    # 下载图片
                    img_resp = client.get(img_url)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filepath = COVER_DIR / f"cover_{timestamp}.png"
                    filepath.write_bytes(img_resp.content)
                    logger.info(f"封面已保存: {filepath}")
                    return str(filepath)

                elif task_status == "FAILED":
                    logger.warning(f"封面生成失败: {status}")
                    return ""

            logger.warning("封面生成超时")
            return ""

        except Exception as e:
            logger.warning(f"封面生成异常: {e}")
            return ""
