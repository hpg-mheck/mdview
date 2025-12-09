from mdview.hyperlinks import Hyperlink, HyperlinkNavigator, normalize_hyperlinks


def test_normalize_hyperlinks_removes_markup() -> None:
    lines = ["See [alpha](https://a.example) and [beta](https://b.example)"]

    cleaned, hyperlinks, hyperlinks_by_line = normalize_hyperlinks(lines)

    assert cleaned == ["See alpha and beta"]
    assert len(hyperlinks) == 2
    assert hyperlinks[0].start == 4
    assert hyperlinks[0].end == 9
    assert hyperlinks[1].start == 14
    assert hyperlinks[1].end == 18
    assert hyperlinks_by_line[0][0].text == "alpha"


def test_navigator_wraps_with_visible_subset() -> None:
    links = [
        Hyperlink(index=0, line=0, start=0, end=4, text="one", target=""),
        Hyperlink(index=1, line=2, start=0, end=3, text="two", target=""),
        Hyperlink(index=2, line=4, start=0, end=5, text="three", target=""),
    ]
    navigator = HyperlinkNavigator(links)

    focus = navigator.focus_next(top=0, height=4)
    assert focus and focus.index == 1  # midpoint selection favors the later link

    focus = navigator.focus_previous(top=0, height=4)
    assert focus and focus.index == 0

    focus = navigator.focus_next(top=4, height=2)
    assert focus and focus.index == 2

    focus = navigator.focus_next(top=0, height=2)
    assert focus and focus.index == 0  # focus snaps to the first visible link
