"""リポジトリ直下用の薄い橋渡しスクリプト。

Pterodactylの汎用Pythonエッグでモノレポ全体をクローンした場合、
`{{PY_FILE}}`変数にサブディレクトリ(`vrc-relay-server/run.py`)を指定できない
(スラッシュがバリデーションで弾かれる等)場合でも、`PY_FILE=run.py`のデフォルト値
のままで`vrc-relay-server/run.py`が起動するようにする。
"""

import runpy
from pathlib import Path

runpy.run_path(
    str(Path(__file__).resolve().parent / "vrc-relay-server" / "run.py"),
    run_name="__main__",
)
