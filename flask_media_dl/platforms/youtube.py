"""Youtube API wrapper"""

from contextlib import ExitStack
from datetime import datetime
import os

from dateutil import parser as dt_parser
from pytube import extract
import requests
import yt_dlp

from flask_media_dl.constants import YOUTUBE, logger
from flask_media_dl.utils import get_slug, load_json, save_json

YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
PLAYLIST_API = f"{YOUTUBE_API}/playlists"
PLAYLIST_ITEMS_API = f"{YOUTUBE_API}/playlistItems"
CHANNEL_SECTIONS_API = f"{YOUTUBE_API}/channelSections"
CHANNELS_API = f"{YOUTUBE_API}/channels"
SEARCH_API = f"{YOUTUBE_API}/search"
VIDEOS_API = f"{YOUTUBE_API}/videos"
MAX_VIDEOS_PER_REQUEST = 50  # for VIDEOS_API
RESULTS_PER_PAGE = 50  # max: 50


class Playlist:
    """Youtube Playlist
    
    :param playlist_id: Youtube playlist ID
    :type playlist_id: str
    :param title: Playlist title
    :type title: str
    :param description: Playlist description
    :type description: str
    :param creator_id: Youtube channel ID of playlist creator
    :type creator_id: str
    :param creator_name: Youtube channel name of playlist creator
    :type creator_name: str
    :param slug: Playlist slug
    :type slug: str
    """
    def __init__(self, playlist_id, title, description, creator_id, creator_name):
        self.playlist_id = playlist_id
        self.title = title
        self.description = description
        self.creator_id = creator_id
        self.creator_name = creator_name
        self.slug = get_slug(title, js_safe=True)

    @classmethod
    def from_id(cls, playlist_id):
        """
        return Playlist object from playlist_id

        :param playlist_id: Youtube playlist ID
        :type playlist_id: str
        :return: Playlist object
        :rtype: Playlist
        """
        playlist_json = get_playlist_json(playlist_id)
        return Playlist(
            playlist_id=playlist_id,
            title=playlist_json["snippet"]["title"],
            description=playlist_json["snippet"]["description"],
            creator_id=playlist_json["snippet"]["channelId"],
            creator_name=playlist_json["snippet"]["channelTitle"],
        )

    def __dict__(self):
        return {
            "playlist_id": self.playlist_id,
            "title": self.title,
            "description": self.description,
            "creator_id": self.creator_id,
            "creator_name": self.creator_name,
            "slug": self.slug.replace("_", "-"),
        }


def credentials_ok():
    """
    check that a Youtube search is successful, validating API_KEY

    :return: True if successful, False otherwise
    :rtype: bool
    """
    req = requests.get(
        SEARCH_API, params={"part": "snippet", "maxResults": 1, "key": YOUTUBE.api_key}
    )
    if req.status_code > 400:
        logger.error(f"HTTP {req.status_code} Error response: {req.text}")
    try:
        req.raise_for_status()
        return bool(req.json()["items"])
    except Exception:
        return False


def get_channel_json(channel_id, for_username=False):
    """
    fetch or retieve-save and return the Youtube ChannelResult JSON
    
    :param channel_id: Youtube channel ID
    :type channel_id: str
    :param for_username: if True, channel_id is a username, not a channel ID
    :type for_username: bool
    :return: Youtube ChannelResult JSON
    :rtype: dict
    """
    fname = f"channel_{channel_id}"
    channel_json = load_json(YOUTUBE.cache_dir, fname)
    if channel_json is None:
        logger.debug(f"query youtube-api for Channel #{channel_id}")
        req = requests.get(
            CHANNELS_API,
            params={
                "forUsername" if for_username else "id": channel_id,
                "part": "brandingSettings,snippet,contentDetails",
                "key": YOUTUBE.api_key,
            },
        )
        if req.status_code > 400:
            logger.error(f"HTTP {req.status_code} Error response: {req.text}")
        req.raise_for_status()
        try:
            channel_json = req.json()["items"][0]
        except (KeyError, IndexError):
            if for_username:
                logger.error(f"Invalid username `{channel_id}`: Not Found")
            else:
                logger.error(f"Invalid channelId `{channel_id}`: Not Found")
            raise
        save_json(YOUTUBE.cache_dir, fname, channel_json)
    return channel_json


def get_channel_playlists_json(channel_id, optimize_number):
    """
    fetch or retieve-save and return the Youtube Playlists JSON for a channel
    
    :param channel_id: Youtube channel ID
    :type channel_id: str
    :param optimize_number: if >= 3, merge playlists with less than <optimize_number> videos into one playlist
    :type optimize_number: int
    :return: Youtube Playlists JSON
    :rtype: dict
    """
    fname = f"channel_{channel_id}_playlists"
    channel_playlists_json = load_json(YOUTUBE.cache_dir, fname)

    items = load_json(YOUTUBE.cache_dir, fname)
    if items is not None:
        if optimize_number is None:
            return items
        
        if optimize_number >= 3:
            items = merge_playlists(channel_id, items, optimize_number)

        if optimize_number == 0:
            items = merge_playlists(channel_id, items, 0)

        if optimize_number == 1 or optimize_number == 2:
            raise ValueError("optimize_number must be 0 or >= 3")

        return items

    logger.debug(f"query youtube-api for Playlists of channel #{channel_id}")

    items = []
    page_token = None
    while True:
        req = requests.get(
            PLAYLIST_API,
            params={
                "channelId": channel_id,
                "part": "id",
                "key": YOUTUBE.api_key,
                "maxResults": RESULTS_PER_PAGE,
                "pageToken": page_token,
            },
        )
        if req.status_code > 400:
            logger.error(f"HTTP {req.status_code} Error response: {req.text}")
        req.raise_for_status()
        channel_playlists_json = req.json()
        items += channel_playlists_json["items"]
        save_json(YOUTUBE.cache_dir, fname, items)
        page_token = channel_playlists_json.get("nextPageToken")
        if not page_token:
            break
    return items


def merge_playlists(channel_id, items, optimize_number):
    """ 
    merge playlists with less than <optimize_number> videos into one playlist

    :param channel_id: Youtube channel ID
    :type channel_id: str
    :param items: Youtube Playlists JSON
    :type items: dict
    :param optimize_number: <optimize_number> videos
    :type optimize_number: int
    :return: Youtube Playlists JSON
    :rtype: dict
    """

    items_merged = []
    for item in items:
        playlist_id = item["id"]
        playlist_json = load_json(YOUTUBE.cache_dir, f"playlist_{playlist_id}_videos")

        if optimize_number >= 3:
            if len(playlist_json) < optimize_number:
                items_merged += playlist_json
  
                os.remove(os.path.join(YOUTUBE.cache_dir, f"playlist_{playlist_id}_videos.json"))
                os.remove(os.path.join(YOUTUBE.cache_dir, f"playlist_{playlist_id}.json"))

                channel_playlists_json = load_json(
                    YOUTUBE.cache_dir, f"channel_{channel_id}_playlists"
                )
                channel_playlists_json.remove(item)
                save_json(
                    YOUTUBE.cache_dir, f"channel_{channel_id}_playlists", channel_playlists_json
                )

        elif optimize_number == 0:
            items_merged += playlist_json

            os.remove(os.path.join(YOUTUBE.cache_dir, f"playlist_{playlist_id}_videos.json"))
            os.remove(os.path.join(YOUTUBE.cache_dir, f"playlist_{playlist_id}.json"))

            channel_playlists_json = load_json(
                YOUTUBE.cache_dir, f"channel_{channel_id}_playlists"
            )
            channel_playlists_json.remove(item)
            save_json(YOUTUBE.cache_dir, f"channel_{channel_id}_playlists", channel_playlists_json)

    channel_json = load_json(YOUTUBE.cache_dir, f"channel_{channel_id}")
    upload_id = channel_json["contentDetails"]["relatedPlaylists"]["uploads"]
    uploads_playlist_json = load_json(YOUTUBE.cache_dir, f"playlist_{upload_id}_videos")

    if optimize_number == 0 or (
        optimize_number >= 3 and len(uploads_playlist_json) < optimize_number
    ):
        items_merged += uploads_playlist_json

        os.remove(os.path.join(YOUTUBE.cache_dir, f"playlist_{upload_id}_videos.json"))
        os.remove(os.path.join(YOUTUBE.cache_dir, f"playlist_{upload_id}.json"))

        channel_playlists_json = load_json(YOUTUBE.cache_dir, f"channel_{channel_id}_playlists")
        for item in channel_playlists_json:
            if item["id"] == upload_id:
                channel_playlists_json.remove(item)
                break
        save_json(YOUTUBE.cache_dir, f"channel_{channel_id}_playlists", channel_playlists_json)

    new_channel_playlists_json = {
        "kind": "youtube#playlist",
        "etag": "custom",
        "id": "custom",
    }

    save_json(YOUTUBE.cache_dir, f"channel_{channel_id}_playlists", new_channel_playlists_json)

    playlist_json = {
        "kind": "youtube#playlist",
        "etag": "custom",
        "id": "custom",
        "snippet": {
            "title": "Other Videos" if optimize_number >= 3 else "All Videos",
            "description": "Custom playlist created by user",
            "channelId": channel_id,
            "channelTitle": channel_json["snippet"]["title"],
        },
    }
    save_json(YOUTUBE.cache_dir, "playlist_custom", playlist_json)

    playlist_json = items_merged

    # remove whole duplicated items from the playlist_json
    videos_ids = []
    unique_videos_ids = []
    for item in playlist_json:
        video_id = item["contentDetails"]["videoId"]
        if video_id not in videos_ids:
            videos_ids.append(video_id)
            unique_videos_ids.append(item)
    playlist_json = unique_videos_ids

    # update the video position in the playlist_json
    for i, item in enumerate(playlist_json):
        item["snippet"]["position"] = i

    # save the playlist_<playlist_id>_videos.json
    save_json(YOUTUBE.cache_dir, "playlist_custom_videos", playlist_json)
    # return the channel_playlists_json
    return new_channel_playlists_json


def get_playlist_json(playlist_id):
    """fetch or retieve-save and return the Youtube PlaylistResult JSON"""
    fname = f"playlist_{playlist_id}"
    playlist_json = load_json(YOUTUBE.cache_dir, fname)
    if playlist_json is None:
        logger.debug(f"query youtube-api for Playlist #{playlist_id}")
        req = requests.get(
            PLAYLIST_API,
            params={"id": playlist_id, "part": "snippet", "key": YOUTUBE.api_key},
        )
        if req.status_code > 400:
            logger.error(f"HTTP {req.status_code} Error response: {req.text}")
        req.raise_for_status()
        try:
            playlist_json = req.json()["items"][0]
        except IndexError:
            logger.error(f"Invalid playlistId `{playlist_id}`: Not Found")
            raise
        save_json(YOUTUBE.cache_dir, fname, playlist_json)
    return playlist_json


def get_videos_json(playlist_id):
    """retrieve a list of youtube PlaylistItem dict

    same request for both channel and playlist
    channel mode uses `uploads` playlist from channel"""

    fname = f"playlist_{playlist_id}_videos"
    items = load_json(YOUTUBE.cache_dir, fname)
    if items is not None:
        return items

    logger.debug(f"query youtube-api for PlaylistItems of playlist #{playlist_id}")

    items = []
    page_token = None
    while True:
        req = requests.get(
            PLAYLIST_ITEMS_API,
            params={
                "playlistId": playlist_id,
                "part": "snippet,contentDetails,status",
                "key": YOUTUBE.api_key,
                "maxResults": RESULTS_PER_PAGE,
                "pageToken": page_token,
            },
        )
        if req.status_code > 400:
            logger.error(f"HTTP {req.status_code} Error response: {req.text}")
        req.raise_for_status()
        videos_json = req.json()
        items += videos_json["items"]
        page_token = videos_json.get("nextPageToken")
        if not page_token:
            break

    save_json(YOUTUBE.cache_dir, fname, items)
    return items


def get_video_json(videos_ids):
    """fetch or retieve-save and return the Youtube VideoResult JSON"""
    views_per_year = {}
    videos_size = {}
    all_videos_json = []
    logger.debug(f"we will fetch {len(videos_ids)} videos")
    # we fetch the videos in chunks of 50
    for i in range(0, len(videos_ids), 50):
        video_ids_chunk = videos_ids[i : i + 50]
        req = requests.get(
            VIDEOS_API,
            params={
                "id": ",".join(video_ids_chunk),
                "part": "snippet,contentDetails,statistics",
                "key": YOUTUBE.api_key,
            },
        )
        if req.status_code > 400:
            logger.error(f"HTTP {req.status_code} Error response: {req.text}")
        req.raise_for_status()
        videos_json = req.json()
        all_videos_json += videos_json["items"]
    for video in all_videos_json:
        logger.debug(f"fetching video {all_videos_json.index(video) + 1}/{len(all_videos_json)}")
        video_id = video["id"]
        # we add in statistics the view_per_year and video_size
        views = int(video["statistics"]["viewCount"])
        published_at = datetime.strptime(video["snippet"]["publishedAt"], "%Y-%m-%dT%H:%M:%SZ")
        now = datetime.now()
        years = now.year - published_at.year

        try:
            view_per_year = int(views / years + 1)
        except ZeroDivisionError:
            view_per_year = 0
        views_per_year[video_id] = view_per_year

        options = {
            "ignoreerrors": True,
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            try:
                info = ydl.extract_info(video_id, download=False)
                video_size = info["filesize_approx"]
                videos_size[video_id] = video_size
                logger.debug(f"{info['title']} is {video_size / 1024 / 1024} MB")
            except:
                videos_size[video_id] = 0
                logger.debug(f"video {video_id} is not available")
    # we add the views_per_year and video_size to the statistics dict
    for video in all_videos_json:
        video_id = video["id"]
        video["statistics"]["viewPerYear"] = views_per_year[video_id]
        video["statistics"]["videoSize"] = videos_size[video_id]
    return all_videos_json


def subset_videos_json(videos, subset_by, subset_videos, subset_gb):
    """filter the videos by a subset of videos"""
    # we sort the videos by views or recent or views-per-year
    if subset_by == "views":
        videos = sorted(videos, key=lambda video: video["statistics"]["viewCount"], reverse=True)
    elif subset_by == "recent":
        videos = sorted(videos, key=lambda video: video["snippet"]["publishedAt"], reverse=True)
    elif subset_by == "views-per-year":
        videos = sorted(videos, key=lambda video: video["statistics"]["viewPerYear"], reverse=True)
    if subset_videos != 0:
        videos_ids = [video["id"] for video in videos]
        videos_ids_subset = videos_ids[:subset_videos]
        videos = [video for video in videos if video["id"] in videos_ids_subset]
    if subset_gb != 0:
        # subset_gb is in gigabytes, convert to bytes
        subset_gb = subset_gb * 1024 * 1024 * 1024
        total_size = 0
        videos_ids_subset = []
        videos = sorted(videos, key=lambda video: video["statistics"]["viewPerYear"], reverse=True)
        for video in videos:
            video_id = video["id"]
            video_size = video["statistics"]["videoSize"]
            if total_size + video_size <= subset_gb:
                total_size += video_size
                videos_ids_subset.append(video_id)
                if video_id == videos_ids[-1]:
                    videos_ids = videos_ids_subset
                    videos = [video for video in videos if video["id"] in videos_ids]
                    break
            else:
                videos_ids = videos_ids_subset
                videos = [video for video in videos if video["id"] in videos_ids]
                break
    return videos


def replace_titles(items, custom_titles):
    """replace video titles with custom titles from file"""
    # get the list of custom titles files
    logger.debug(f"found {len(custom_titles)} custom titles files")
    # raise an error if there are not exactly 2 custom titles files
    if len(custom_titles) == 0:
        logger.error("no custom titles files found")
        raise ValueError("no custom titles files found")
    elif len(custom_titles) == 1:
        logger.error("only one custom titles file found (need one for titles and one for ids)")
        raise ValueError("only one custom titles file found")
    elif len(custom_titles) > 2:
        logger.error("too many custom titles files found (need one for titles and one for ids)")
        raise ValueError("too many custom titles files found")
    custom_titles_files = custom_titles
    titles = []
    ids = []

    # iterate through the files in custom_titles_files
    with ExitStack() as stack:
        files = [stack.enter_context(open(fname)) for fname in custom_titles_files]
        for f in files:
            logger.debug(f"found {len(f.readlines())} custom titles in {f.name}")
            f.seek(0)
            for line in f:
                if line.startswith("https://"):
                    ids.append(extract.video_id(line))
                    logger.debug(f"found video id {ids[-1]}")
                else:
                    titles.append(line.rstrip())
                    logger.debug(f"found title {titles[-1]}")

        if len(titles) != len(ids):
            logger.error(f"number of titles ({len(titles)}) and ids ({len(ids)}) do not match")
            raise ValueError("number of titles and ids do not match")

        if len(ids) != len(set(ids)):
            logger.error(f"duplicate ids found in {custom_titles_files[1]}: {ids}")

    v_index = 0
    for item in items:
        if v_index < len(ids):
            while v_index < len(ids) and item["contentDetails"]["videoId"] != ids[v_index]:
                v_index += 1
            if v_index < len(ids):
                logger.info(f"replacing {item['snippet']['title']} with {titles[v_index]}")
                item["snippet"]["title"] = titles[v_index]
                v_index += 1
        else:
            logger.debug("no more titles to replace")
            break


def get_videos_authors_info(videos_ids):
    """query authors' info for each video from their relative channel"""

    items = load_json(YOUTUBE.cache_dir, "videos_channels")

    if items is not None:
        return items

    logger.debug(f"query youtube-api for Video details of {len(videos_ids)} videos")

    items = {}

    def retrieve_videos_for(videos_ids):
        """{videoId: {channelId: channelTitle}} for all videos_ids"""
        req_items = {}
        page_token = None
        while True:
            req = requests.get(
                VIDEOS_API,
                params={
                    "id": ",".join(videos_ids),
                    "part": "snippet, contentDetails, statistics",
                    "key": YOUTUBE.api_key,
                    "maxResults": RESULTS_PER_PAGE,
                    "pageToken": page_token,
                },
            )
            if req.status_code > 400:
                logger.error(f"HTTP {req.status_code} Error response: {req.text}")
            req.raise_for_status()
            videos_json = req.json()
            for item in videos_json["items"]:
                req_items.update(
                    {
                        item["id"]: {
                            "channelId": item["snippet"]["channelId"],
                            "channelTitle": item["snippet"]["channelTitle"],
                            item["statistics"]["viewPerYear"]: int(
                                int(item["statistics"]["viewCount"])
                                / (
                                    datetime.now().year
                                    - (int(item["snippet"]["publishedAt"][:4] + 1))
                                )
                            ),
                        }
                    }
                )
            page_token = videos_json.get("nextPageToken")
            if not page_token:
                break
        return req_items

    # split it over n requests so that each request includes
    # as most MAX_VIDEOS_PER_REQUEST videoId to avoid too-large URI issue
    for interv in range(0, len(videos_ids), MAX_VIDEOS_PER_REQUEST):
        items.update(retrieve_videos_for(videos_ids[interv : interv + MAX_VIDEOS_PER_REQUEST]))

    save_json(YOUTUBE.cache_dir, "videos_channels", items)

    return items


def skip_deleted_videos(item):
    """filter func to filter-out deleted, unavailable or private videos"""
    return (
        item["snippet"]["title"] != "Deleted video"
        and item["snippet"]["description"] != "This video is unavailable."
        and item["status"]["privacyStatus"] != "private"
    )


def skip_outofrange_videos(date_range, item):
    """filter func to filter-out videos that are not within specified date range"""
    return dt_parser.parse(item["snippet"]["publishedAt"]).date() in date_range


def extract_playlists_details_from(collection_type, youtube_id, optimize_number):
    """prepare a list of Playlist from user request

    USER: we fetch the hidden channel associate to it
    CHANNEL (and USER): we grab all playlists + `uploads` playlist
    PLAYLIST: we retrieve from the playlist Id(s)"""

    uploads_playlist_id = None
    main_channel_id = None
    if collection_type == "user" or collection_type == "channel":
        if collection_type == "user":
            # youtube_id is a Username, fetch actual channelId through channel
            channel_json = get_channel_json(youtube_id, for_username=True)
        else:
            # youtube_id is a channelId
            channel_json = get_channel_json(youtube_id)

        main_channel_id = channel_json["id"]

        # retrieve list of playlists for that channel
        # playlist_ids = [p["id"] for p in get_channel_playlists_json(main_channel_id, optimize_number)]
        channel_playlists_json = get_channel_playlists_json(main_channel_id, optimize_number)
        if optimize_number == 0:
            playlist_ids = ["custom"]
        else:
            playlist_ids = [p["id"] for p in channel_playlists_json]
            # we always include uploads playlist (contains everything)
            playlist_ids += [channel_json["contentDetails"]["relatedPlaylists"]["uploads"]]
            uploads_playlist_id = playlist_ids[-1]

    elif collection_type == "playlist":
        playlist_ids = youtube_id.split(",")
        main_channel_id = Playlist.from_id(playlist_ids[0]).creator_id
    else:
        raise NotImplementedError("unsupported collection_type")

    return (
        [Playlist.from_id(playlist_id) for playlist_id in list(set(playlist_ids))],
        main_channel_id,
        uploads_playlist_id,
    )
