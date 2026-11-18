"""실행: python -m mydaf            → 화면
        python -m mydaf once [주제] → 화면 없이 한 편 실행
        python -m mydaf loop        → 화면 없이 연속 실행"""
import sys


def cli():
    args = sys.argv[1:]
    if not args:
        from .gui import main
        return main()
    from .config import Config
    from .runner import Runner
    cfg = Config.load()
    runner = Runner(cfg)
    if args[0] == "once":
        print(runner.run_once(" ".join(args[1:]) or None))
    elif args[0] == "loop":
        from .remote import RemoteControl
        RemoteControl(cfg, runner).start()
        runner.start()
        try:
            runner.thread.join()
        except KeyboardInterrupt:
            runner.stop()
    else:
        print(__doc__)


if __name__ == "__main__":
    cli()
