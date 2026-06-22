from __future__ import annotations

from ai_media_assistant.clients.pt.web import WebPTSearchClient
from ai_media_assistant.shared.config import get_settings
from ai_media_assistant.shared.schemas import SearchQuery


def test_web_parse_extracts_metadata_from_row_text():
    html = """
    <html><body>
      <table>
        <tr>
          <td><a href="details.php?id=1869" title="Sherlock Holmes 2009 2160p UHD BluRay REMUX">Sherlock Holmes 2009 2160p UHD BluRay REMUX</a></td>
          <td>Movie</td>
          <td>78.5 GB</td>
          <td>Seeders: 120</td>
          <td><a href="download.php?id=1869">下载本种</a></td>
        </tr>
      </table>
    </body></html>
    """

    client = WebPTSearchClient()
    items = client._parse_html(html, limit=10)

    assert len(items) == 1
    one = items[0]
    assert one.category == "Movie"
    assert one.resolution == "2160P"
    assert one.quality == "BLURAY"
    assert one.seeders == 120
    assert one.size_bytes > 0
    assert one.download_url


def test_build_search_url_with_param_mapping(monkeypatch):
    monkeypatch.setenv("PT_BASE_URL", "https://pt.example/torrents.php")
    monkeypatch.setenv("PT_COOKIE", "uid=1")
    monkeypatch.setenv("PT_WEB_KEYWORD_PARAM", "searchstr")
    monkeypatch.setenv("PT_WEB_CATEGORY_PARAM", "cat")
    monkeypatch.setenv("PT_WEB_CATEGORY_PARAM_MAP", "")
    monkeypatch.setenv("PT_WEB_QUALITY_PARAM", "source")
    get_settings.cache_clear()

    client = WebPTSearchClient()
    url = client._build_search_url(
        SearchQuery(keyword="Dune", category="Movie", quality="BluRay"),
        page=2,
    )

    assert "searchstr=Dune" in url
    assert "cat=Movie" in url
    assert "source=BluRay" in url
    assert "page=2" in url


def test_build_search_url_with_category_param_map_multiselect(monkeypatch):
    monkeypatch.setenv("PT_BASE_URL", "https://audiences.me/torrents.php?incldead=0")
    monkeypatch.setenv("PT_COOKIE", "uid=1")
    monkeypatch.setenv("PT_WEB_KEYWORD_PARAM", "search")
    monkeypatch.setenv(
        "PT_WEB_CATEGORY_PARAM_MAP",
        '{"电影":"cat401","剧集":"cat402","综艺":"cat403","纪录片":"cat406","音乐":"cat408"}',
    )
    get_settings.cache_clear()

    client = WebPTSearchClient()
    url = client._build_search_url(
        SearchQuery(keyword="大侦探", category="电影,剧集,综艺"),
        page=1,
    )

    assert "search=%E5%A4%A7%E4%BE%A6%E6%8E%A2" in url
    assert "incldead=0" in url
    assert "cat401=1" in url
    assert "cat402=1" in url
    assert "cat403=1" in url


def test_build_search_url_with_template(monkeypatch):
    monkeypatch.setenv("PT_BASE_URL", "https://pt.example/torrents.php")
    monkeypatch.setenv("PT_COOKIE", "uid=1")
    monkeypatch.setenv(
        "PT_WEB_QUERY_TEMPLATE",
        "https://pt.example/torrents.php?incldead=1&search={keyword}&cat={category}&std={resolution}&src={quality}&page={page}",
    )
    get_settings.cache_clear()

    client = WebPTSearchClient()
    url = client._build_search_url(
        SearchQuery(
            keyword="Sherlock Holmes",
            category="Movie",
            resolution="2160P",
            quality="BluRay",
        ),
        page=3,
    )

    assert "incldead=1" in url
    assert "search=Sherlock%20Holmes" in url
    assert "cat=Movie" in url
    assert "std=2160P" in url
    assert "src=BluRay" in url
    assert "page=3" in url
