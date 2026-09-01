import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    root.handlers.clear()
    root.addHandler(handler)

    # アクセスログ等はINFOのまま、sqlalchemyのSQLログはWARNING以上に抑制
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
