from importlib.resources import files, as_file
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

_loaded=False


def load_local_font():
    global _loaded
    if _loaded:return
    resource=files("experiment_planner").joinpath("resources/fonts/NotoSansCJK-Regular.ttc")
    with as_file(resource) as path:
        identifier=QFontDatabase.addApplicationFont(str(path))
    if identifier<0:raise RuntimeError("随包中文字体无法加载，请检查安装资源")
    families=QFontDatabase.applicationFontFamilies(identifier)
    family=next((f for f in families if f=="Noto Sans CJK SC"),families[0])
    QApplication.instance().setFont(QFont(family,10))
    _loaded=True
