"""同目录临时文件 + os.replace，避免覆盖写中断后留下半个文件。"""

import json
import os
import tempfile


def write_text_atomic(path: str, content: str, encoding: str = "utf-8") -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding=encoding, dir=directory, delete=False
        ) as tmp:
            temp_path = tmp.name
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


def write_json_atomic(path: str, data, *, indent: int = 2) -> None:
    write_text_atomic(
        path,
        json.dumps(data, ensure_ascii=False, indent=indent),
    )
