"""从 ModelScope 下载 Qwen3-ASR-1.7B 模型。"""
from modelscope import snapshot_download
path = snapshot_download("Qwen/Qwen3-ASR-1.7B", cache_dir="/srv/mengasr/models/")
print("OK:", path)
