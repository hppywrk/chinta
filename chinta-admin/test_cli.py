from cli import build_parser


def test_parser_user_create():
    parser = build_parser()
    args = parser.parse_args(["--output", "json", "user", "create", "--email", "a@b.c"])
    assert args.email == "a@b.c"
    assert args.output == "json"
