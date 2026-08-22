from main_exe import run

PAIR = "AUD_USD"


def main(*, dry_run=False, application=None, max_ticks=None):
    return run(
        PAIR,
        dry_run=dry_run,
        application=application,
        max_ticks=max_ticks,
    )


if __name__ == "__main__":
    main()
