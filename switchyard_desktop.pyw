import sys

from switchyard_daily import SwitchyardDailyApp


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    # Packaging/CI probe: import the complete desktop dependency graph without
    # creating a Tk root. This catches missing PyInstaller modules while remaining
    # safe on headless and unattended release runners.
    if '--smoke-test' in args:
        return 0
    SwitchyardDailyApp().mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
