"""Tests for the museum source ports, against recorded API responses."""

import re

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.remart.sources import (
    KEYLESS_SOURCES,
    SOURCES,
)
from custom_components.remart.sources.museums import (
    ChicagoSource,
    ClevelandSource,
    EuropeanaSource,
    MetSource,
    MiaSource,
    RijksSource,
    SmithsonianSource,
    SmkSource,
)
from custom_components.remart.sources.photos import PixabaySource, UnsplashSource
from custom_components.remart.sources.wikimedia import WikimediaSource

from .conftest import load_fixture


def test_registry() -> None:
    """Museums plus photo libraries; keyed ones are not default."""
    assert set(SOURCES) == {
        "chicago",
        "met",
        "cleveland",
        "smk",
        "mia",
        "wikimedia",
        "rijks",
        "europeana",
        "smithsonian",
        "unsplash",
        "pixabay",
    }
    assert set(KEYLESS_SOURCES) == {
        "chicago",
        "met",
        "cleveland",
        "smk",
        "mia",
        "wikimedia",
    }


async def test_chicago(hass: HomeAssistant, aioclient_mock) -> None:
    """Chicago builds IIIF URLs from image_id."""
    aioclient_mock.post(
        "https://api.artic.edu/api/v1/artworks/search",
        json=load_fixture("chicago.json"),
    )
    page = await ChicagoSource(async_get_clientsession(hass)).fetch_page(1, 2)
    assert len(page) == 2
    art = page[0]
    assert art.source_id == "chicago"
    assert re.fullmatch(
        r"https://lakeimagesweb\.artic\.edu/iiif/2/[\w-]+/full/1686,/0/default\.jpg",
        art.image_url,
    )
    assert art.thumb_url.endswith("/full/400,/0/default.jpg")
    assert art.title and art.artist
    sent = aioclient_mock.mock_calls[0][2]
    assert sent["page"] == 1 and sent["limit"] == 2


async def test_met(hass: HomeAssistant, aioclient_mock) -> None:
    """Met pages via v1.1 search; skips frames and objects without open image."""
    aioclient_mock.get(
        re.compile(
            r"https://collectionapi\.metmuseum\.org/public/collection/v1\.1/search.*"
        ),
        json={"total": 4, "objectIDs": [436535, 2, 3, 4]},
    )
    base = "https://collectionapi.metmuseum.org/public/collection/v1/objects"
    aioclient_mock.get(f"{base}/436535", json=load_fixture("met_object.json"))
    aioclient_mock.get(f"{base}/2", json={"primaryImage": ""})
    aioclient_mock.get(
        f"{base}/3",
        json={
            "primaryImage": "https://x/frame.jpg",
            "classification": "Frames",
            "isPublicDomain": True,
        },
    )
    aioclient_mock.get(
        f"{base}/4",
        json={"primaryImage": "https://x/licensed.jpg", "isPublicDomain": False},
    )
    page = await MetSource(async_get_clientsession(hass)).fetch_page(3, 20)
    assert [a.id for a in page] == ["436535"]
    assert page[0].image_url.startswith("https://images.metmuseum.org/")
    search_url = aioclient_mock.mock_calls[0][1]
    assert search_url.query["offset"] == "40"
    assert search_url.query["limit"] == "20"
    assert search_url.query["departmentId"] == "11"

    # The API serves only the first 10,000 results.
    source = MetSource(async_get_clientsession(hass))
    calls = aioclient_mock.call_count
    assert await source.fetch_page(501, 20) == []
    assert aioclient_mock.call_count == calls


async def test_cleveland(hass: HomeAssistant, aioclient_mock) -> None:
    """Cleveland uses the web image and the first creator."""
    aioclient_mock.get(
        re.compile(r"https://openaccess-api\.clevelandart\.org/api/artworks/.*"),
        json=load_fixture("cleveland.json"),
    )
    page = await ClevelandSource(async_get_clientsession(hass)).fetch_page(2, 2)
    assert len(page) == 2
    assert page[0].image_url.endswith("_web.jpg")
    assert page[0].artist
    assert aioclient_mock.mock_calls[0][1].query["skip"] == "2"


async def test_smk(hass: HomeAssistant, aioclient_mock) -> None:
    """SMK takes the first title, artist and production period."""
    aioclient_mock.get(
        re.compile(r"https://api\.smk\.dk/api/v1/art/search.*"),
        json=load_fixture("smk.json"),
    )
    page = await SmkSource(async_get_clientsession(hass)).fetch_page(1, 2)
    assert len(page) == 2
    assert page[0].title != "Untitled"
    assert page[0].license_text == "CC BY"


async def test_mia(hass: HomeAssistant, aioclient_mock) -> None:
    """Mia keeps the literal '+' in its search path."""
    aioclient_mock.get(
        re.compile(r"https://search\.artsmia\.org/rights_type:Public\+Domain.*"),
        json=load_fixture("mia.json"),
    )
    page = await MiaSource(async_get_clientsession(hass)).fetch_page(1, 2)
    assert page
    assert re.fullmatch(r"https://4\.api\.artsmia\.org/800/\d+\.jpg", page[0].image_url)
    assert "Public+Domain" in str(aioclient_mock.mock_calls[0][1])


async def test_wikimedia_paging(hass: HomeAssistant, aioclient_mock) -> None:
    """Wikimedia only pages forward with continue tokens and strips HTML."""
    members = load_fixture("wikimedia_members.json")
    members["continue"] = {"cmcontinue": "file|NEXT"}
    aioclient_mock.get(
        re.compile(
            r"https://commons\.wikimedia\.org/w/api\.php\?.*list=categorymembers.*"
        ),
        json=members,
    )
    aioclient_mock.get(
        re.compile(r"https://commons\.wikimedia\.org/w/api\.php\?.*pageids=.*"),
        json=load_fixture("wikimedia_info.json"),
    )
    source = WikimediaSource(async_get_clientsession(hass))
    assert await source.fetch_page(3, 2) == []

    page = await source.fetch_page(1, 2)
    assert len(page) == 2
    for art in page:
        assert art.image_url.startswith("https://upload.wikimedia.org/")
        assert " " not in art.image_url and "(" not in art.image_url
        assert art.artist is None or "<" not in art.artist

    await source.fetch_page(2, 2)
    assert aioclient_mock.mock_calls[-2][1].query["cmcontinue"] == "file|NEXT"


async def test_keyed_sources_need_key(hass: HomeAssistant, aioclient_mock) -> None:
    """Without a key, keyed sources return nothing and make no request."""
    session = async_get_clientsession(hass)
    for cls in (
        RijksSource,
        EuropeanaSource,
        SmithsonianSource,
        UnsplashSource,
        PixabaySource,
    ):
        assert await cls(session).fetch_page(1, 20) == []
    assert aioclient_mock.call_count == 0


async def test_europeana(hass: HomeAssistant, aioclient_mock) -> None:
    """Europeana sends both qf filters and labels the license."""
    aioclient_mock.get(
        re.compile(r"https://api\.europeana\.eu/record/v2/search\.json.*"),
        json={
            "items": [
                {
                    "id": "/2048/abc",
                    "edmIsShownBy": ["https://e/full.jpg"],
                    "edmPreview": ["https://e/thumb.jpg"],
                    "title": ["Seascape"],
                    "dcCreator": ["Someone"],
                    "year": ["1890"],
                    "rights": ["http://creativecommons.org/publicdomain/mark/1.0/"],
                },
                {"id": "/1/no-image"},
            ]
        },
    )
    page = await EuropeanaSource(async_get_clientsession(hass), "key").fetch_page(2, 20)
    assert len(page) == 1
    assert page[0].id == "/2048/abc"
    assert page[0].license_text == "Public Domain"
    query = aioclient_mock.mock_calls[0][1].query
    assert query.getall("qf") == ["TYPE:IMAGE", "RIGHTS:*open*"]
    assert query["start"] == "21"


async def test_rijks_and_smithsonian(hass: HomeAssistant, aioclient_mock) -> None:
    """Rijks and Smithsonian parse their nested image fields."""
    aioclient_mock.get(
        re.compile(r"https://www\.rijksmuseum\.nl/api/en/collection.*"),
        json={
            "artObjects": [
                {
                    "objectNumber": "SK-C-5",
                    "title": "The Night Watch",
                    "principalOrFirstMaker": "Rembrandt",
                    "webImage": {"url": "https://r/full.jpg"},
                    "headerImage": {"url": "https://r/head.jpg"},
                    "dating": {"presentingDate": "1642"},
                }
            ]
        },
    )
    aioclient_mock.get(
        re.compile(r"https://api\.si\.edu/openaccess/api/v1\.0/search.*"),
        json={
            "response": {
                "rows": [
                    {
                        "id": "edanmdm-1",
                        "title": "Fallback",
                        "content": {
                            "descriptiveNonRepeating": {
                                "title": {"content": "Mountain Lake"},
                                "online_media": {
                                    "media": [
                                        {"type": "3d"},
                                        {
                                            "type": "Images",
                                            "content": "https://s/i.jpg",
                                            "thumbnail": "https://s/t.jpg",
                                        },
                                    ]
                                },
                            },
                            "freetext": {
                                "name": [
                                    {"label": "Owner", "content": "X"},
                                    {"label": "Creator", "content": "Bierstadt"},
                                ],
                                "date": [{"content": "1870s"}],
                            },
                        },
                    }
                ]
            }
        },
    )
    session = async_get_clientsession(hass)
    (rijks,) = await RijksSource(session, "k").fetch_page(1, 20)
    assert (rijks.id, rijks.title, rijks.artist, rijks.date) == (
        "SK-C-5",
        "The Night Watch",
        "Rembrandt",
        "1642",
    )
    (si,) = await SmithsonianSource(session, "k").fetch_page(1, 20)
    assert (si.title, si.artist, si.date, si.image_url) == (
        "Mountain Lake",
        "Bierstadt",
        "1870s",
        "https://s/i.jpg",
    )


async def test_pixabay(hass: HomeAssistant, aioclient_mock) -> None:
    """Pixabay searches the configured terms and stops at its 500 hit limit."""
    aioclient_mock.get(
        "https://pixabay.com/api/",
        json={
            "totalHits": 500,
            "hits": [
                {
                    "id": 195893,
                    "tags": "blossom, bloom, flower, spring",
                    "largeImageURL": "https://pixabay.com/get/large.jpg",
                    "webformatURL": "https://pixabay.com/get/web.jpg",
                    "user": "Josch13",
                },
                {"id": 2, "tags": "", "previewURL": "https://p/no-large.jpg"},
            ],
        },
    )
    source = PixabaySource(async_get_clientsession(hass), "key", "foggy forest")
    (art,) = await source.fetch_page(2, 20)
    assert (art.id, art.title, art.artist) == (
        "195893",
        "Blossom, bloom, flower",
        "Josch13",
    )
    assert art.image_url == "https://pixabay.com/get/large.jpg"
    assert art.thumb_url == "https://pixabay.com/get/web.jpg"
    query = aioclient_mock.mock_calls[0][1].query
    assert (query["key"], query["q"], query["page"], query["per_page"]) == (
        "key",
        "foggy forest",
        "2",
        "20",
    )
    assert await source.fetch_page(26, 20) == []
    assert aioclient_mock.call_count == 1


async def test_unsplash(hass: HomeAssistant, aioclient_mock) -> None:
    """Unsplash asks for a 4K JPEG and reports shown photos."""
    aioclient_mock.get(
        "https://api.unsplash.com/search/photos",
        json={
            "total": 1,
            "total_pages": 1,
            "results": [
                {
                    "id": "Dwu85P9SOIk",
                    "created_at": "2016-05-03T11:00:28Z",
                    "description": None,
                    "alt_description": "green mountains under a cloudy sky",
                    "urls": {
                        "raw": "https://images.unsplash.com/photo-1?ixid=abc",
                        "full": "https://images.unsplash.com/photo-1?full",
                        "small": "https://images.unsplash.com/photo-1?w=400",
                    },
                    "user": {"name": "Jane Doe"},
                    "links": {
                        "download_location": (
                            "https://api.unsplash.com/photos/Dwu85P9SOIk/download"
                        )
                    },
                }
            ],
        },
    )
    aioclient_mock.get(
        "https://api.unsplash.com/photos/Dwu85P9SOIk/download", json={"url": "x"}
    )
    source = UnsplashSource(async_get_clientsession(hass), "access", None)
    (art,) = await source.fetch_page(1, 20)
    assert art.title == "green mountains under a cloudy sky"
    assert (art.artist, art.date) == ("Jane Doe", "2016-05-03")
    assert art.image_url == (
        "https://images.unsplash.com/photo-1?ixid=abc&w=3840&fm=jpg&q=85&fit=max"
    )
    _, url, _, headers = aioclient_mock.mock_calls[0]
    assert url.query["query"] == "landscape"
    assert headers["Authorization"] == "Client-ID access"

    await source.async_track_use(art)
    assert aioclient_mock.mock_calls[-1][1].path == "/photos/Dwu85P9SOIk/download"

    # Past the last page nothing is returned.
    assert await source.fetch_page(2, 20) == []
