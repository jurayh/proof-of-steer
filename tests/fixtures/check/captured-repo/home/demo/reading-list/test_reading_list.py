import reading_list
def test_add_appends_a_title():
    reading_list.BOOKS.clear()
    reading_list.add("Dune")
    assert reading_list.BOOKS == ["Dune"]
def test_show_prints_the_title(capsys):
    reading_list.BOOKS[:] = []
    reading_list.add("Emma")
    reading_list.show()
    out = capsys.readouterr().out
    assert "Emma" in out
