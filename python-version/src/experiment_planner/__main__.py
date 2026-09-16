import argparse
import multiprocessing
from pathlib import Path


def main():
    multiprocessing.freeze_support()
    parser=argparse.ArgumentParser(description="实验规划助手（Python 源码版）")
    parser.add_argument("--demo",type=Path,help="创建明确标识的合成数据项目，路径不得已存在")
    parser.add_argument("--smoke",action="store_true",help="打开最小 Qt 窗口后自动退出")
    parser.add_argument("--project",type=Path,help="启动时打开已有 SQLite 项目")
    parser.add_argument("--self-test",type=Path,help="执行合成模型、spawn、保存恢复验证；输出目录不得已存在")
    args=parser.parse_args()
    if args.self_test:
        from experiment_planner.application.validation import self_test
        print(self_test(args.self_test))
        return
    if args.demo:
        from experiment_planner.storage.project import Project
        from experiment_planner.application.service import PlannerService
        from experiment_planner.application.synthetic import synthetic_records
        with Project.create(args.demo,"合成案例 — 不代表真实机台") as project:
            service=PlannerService(project)
            for row in synthetic_records(project.template):service.add_record(**row)
        print(f"合成案例已保存：{args.demo}；分母策略仍需显式配置。")
        return
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from experiment_planner.ui.desktop import PythonWindow
    app=QApplication([]);app.setApplicationName("ExperimentPlanner")
    window=PythonWindow()
    if args.project:
        from experiment_planner.storage.project import Project
        window.set_project(Project(args.project))
    window.show()
    if args.smoke:QTimer.singleShot(500,window.close);QTimer.singleShot(600,app.quit)
    return app.exec()


if __name__ == "__main__":raise SystemExit(main())
