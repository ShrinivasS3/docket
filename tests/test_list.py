def _seed(cli):
    cli("idea", "import", "--repo", "TestProj")
    cli(
        "gotcha",
        "--symptom",
        "Boom",
        "--cause",
        "c",
        "--fix",
        "f",
        "--scope",
        "s",
        "--project",
        "OtherProj",
    )


def test_list_all(vault, repo, cli):
    _seed(cli)
    code, out, _ = cli("list")
    assert code == 0
    lines = out.strip().split("\n")
    assert lines[0].split() == ["docket_id", "category", "project", "status", "title"]
    ids = [line.split()[0] for line in lines[1:]]
    assert ids == ["testproj-0001", "testproj-0002", "testproj-0003", "X0001"]
    assert "Boom" in out


def test_list_filters(vault, repo, cli):
    _seed(cli)
    _, out, _ = cli("list", "--category", "Gotchas")
    assert [line.split()[0] for line in out.strip().split("\n")[1:]] == ["X0001"]
    _, out, _ = cli("list", "--status", "In Progress")
    assert [line.split()[0] for line in out.strip().split("\n")[1:]] == [
        "testproj-0003"
    ]
    _, out, _ = cli("list", "--status", "[[Completed]]")
    assert [line.split()[0] for line in out.strip().split("\n")[1:]] == [
        "testproj-0002"
    ]
    _, out, _ = cli("list", "--project", "testproj", "--status", "parked")
    assert [line.split()[0] for line in out.strip().split("\n")[1:]] == [
        "testproj-0001"
    ]
    _, out, _ = cli("list", "--project", "Nobody")
    assert out.strip() == "(no records)"


def test_list_stubs(vault, repo, cli):
    _seed(cli)
    _, out, _ = cli("list", "--stubs")
    ids = [line.split()[0] for line in out.strip().split("\n")[1:]]
    # 0002 is Completed and unjudged, 0003 is In Progress with no gate;
    # 0001 is Parked (neither class) and the gotcha has no verdict axis at all.
    assert ids == ["testproj-0002", "testproj-0003"]
    path = vault.context / "idea-testproj-0002-merged-one.md"
    path.write_text(
        path.read_text().replace("verdict: pending", "verdict: pending\nkind: scaffold")
    )
    _, out, _ = cli("list", "--stubs")
    ids = [line.split()[0] for line in out.strip().split("\n")[1:]]
    assert ids == ["testproj-0003"]
