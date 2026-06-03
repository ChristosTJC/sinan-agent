"""Web 工具测试."""


class TestWebFetch:
    """web_fetch 测试."""

    def test_invalid_url(self):
        from agent.tools.web_tools import web_fetch
        result = web_fetch({"url": "not-a-url"})
        assert result["success"] is False

    def test_bad_protocol(self):
        from agent.tools.web_tools import web_fetch
        result = web_fetch({"url": "ftp://example.com"})
        assert result["success"] is False
        assert "协议" in result.get("error", "")

    def test_empty_url(self):
        from agent.tools.web_tools import web_fetch
        result = web_fetch({"url": ""})
        assert result["success"] is False

    def test_no_args(self):
        from agent.tools.web_tools import web_fetch
        result = web_fetch({})
        assert result["success"] is False

    def test_has_source_field(self, monkeypatch):
        import httpx
        from agent.tools.web_tools import web_fetch

        def fake_get(*args, **kwargs):
            raise httpx.ConnectError("no server")

        monkeypatch.setattr(httpx.Client, "get", fake_get)

        result = web_fetch({"url": "http://localhost:1/no-server-here"})
        assert "source" in result
        assert result["success"] is False


class TestWebSearch:
    """web_search 测试."""

    def test_empty_query(self):
        from agent.tools.web_tools import web_search
        result = web_search({"query": ""})
        assert result["success"] is False

    def test_source_field(self):
        from agent.tools.web_tools import web_search
        result = web_search({"query": "test"})
        assert "source" in result
        assert result["source"] == "duckduckgo"

    def test_returns_results_list(self):
        from agent.tools.web_tools import web_search
        result = web_search({"query": "python programming"})
        assert "results" in result
        assert isinstance(result["results"], list)

    def test_limit_respected(self):
        from agent.tools.web_tools import web_search
        result = web_search({"query": "python", "limit": 3})
        assert len(result["results"]) <= 3

    def test_structured_result(self):
        from agent.tools.web_tools import web_search
        result = web_search({"query": "raspberry pi pico"})
        if result["results"]:
            r0 = result["results"][0]
            assert "title" in r0
            assert "url" in r0
            assert "snippet" in r0


class TestHtmlClean:
    """HTML 清洗测试."""

    def test_strips_tags(self):
        from agent.tools.web_tools import _clean_html
        assert _clean_html("<p>hello</p>") == "hello"
        assert _clean_html("<div><b>bold</b></div>") == "bold"

    def test_removes_script(self):
        from agent.tools.web_tools import _clean_html
        html = '<html><script>alert("xss")</script><p>safe</p></html>'
        cleaned = _clean_html(html)
        assert "alert" not in cleaned
        assert "safe" in cleaned

    def test_removes_style(self):
        from agent.tools.web_tools import _clean_html
        html = '<style>.x{color:red}</style><p>text</p>'
        cleaned = _clean_html(html)
        assert "color" not in cleaned
        assert "text" in cleaned
