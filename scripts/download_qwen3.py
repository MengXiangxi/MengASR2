"""下载 Qwen3-ASR-1.7B 模型。"""
import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from modelscope import snapshot_download
path = snapshot_download("Qwen/Qwen3-ASR-1.7B", cache_dir="/srv/mengasr/models/")
print("downloaded to:", path)
