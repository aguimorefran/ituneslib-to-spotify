import eyed3
import sys
import os
import re
import pandas as pd
import spotipy
import matplotlib.pyplot as plt
from spotipy.oauth2 import SpotifyClientCredentials
from spotipy.oauth2 import SpotifyOAuth
import spotipy.util as util
from tqdm import tqdm


# Load env
from dotenv import load_dotenv
load_dotenv()

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
USERNAME = os.getenv("USERNAME")
REDIRECT_URI = os.getenv("REDIRECT_URI")
PLAYLIST_NAME = os.getenv("PLAYLIST_NAME")

if not CLIENT_ID or not CLIENT_SECRET or not REDIRECT_URI or not USERNAME:
    print("Please set CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, and USERNAME in .env file")
    sys.exit(1)

# If args entered by user != 1, then error
if len(sys.argv) != 2:
    print("Usage: python run.py <music_dir>")
    sys.exit(1)

MUSIC_DIR = sys.argv[1]
ACCEPTED_EXTENSIONS = ["mp3"]
METADATA_TAGS = ['title',
                 'artist',
                 'album']


def remove_emojis(data):
    emoj = re.compile("["
                      u"\U00002700-\U000027BF"  # Dingbats
                      u"\U0001F600-\U0001F64F"  # Emoticons
                      u"\U00002600-\U000026FF"  # Miscellaneous Symbols
                      u"\U0001F300-\U0001F5FF"  # Miscellaneous Symbols And Pictographs
                      u"\U0001F900-\U0001F9FF"  # Supplemental Symbols and Pictographs
                      u"\U0001FA70-\U0001FAFF"  # Symbols and Pictographs Extended-A
                      u"\U0001F680-\U0001F6FF"  # Transport and Map Symbols
                      "]+", re.UNICODE)
    return re.sub(emoj, '', data)


def clean_string(string):
    # Remove trailing symbols
    string = string.strip()
    string = re.sub(r'[^\w\s]', '', string)
    string = string.strip()
    return string


def get_metadata():
    metadata_list = []
    for root, dirs, files in os.walk(MUSIC_DIR):
        for file in files:
            if file.endswith(tuple(ACCEPTED_EXTENSIONS)):
                song_metadata = {}
                clean_filename = remove_emojis(file)
                clean_filepath = os.path.join(root, clean_filename)
                extension = os.path.splitext(clean_filename)[1]

                # Remove extension from filename. Strip from symbols and spaces preceding and following filename
                filename = os.path.splitext(clean_filename)[0]
                filename = re.sub(r'[^\w\s]', '', filename)
                filename = filename.strip()

                song_metadata["filepath"] = clean_filepath
                song_metadata["filename"] = filename
                song_metadata["extension"] = extension

                # Get metadata from file
                try:
                    audiofile = eyed3.load(clean_filepath)
                except Exception as error:
                    print(f"Error loading file {clean_filepath}: {error}")
                    metadata_list.append(song_metadata)
                    continue

                if audiofile is None:
                    metadata_list.append(song_metadata)
                    continue

                # Get metadata from file
                for tag in METADATA_TAGS:
                    val = getattr(audiofile.tag, tag, None)
                    val = clean_string(val) if val else None
                    song_metadata[tag] = val

                metadata_list.append(song_metadata)

    return metadata_list


def get_spotify_data(sp_client, metadata_list):
    seen_spotify_ids = set()
    unique_metadata_list = []

    for song in tqdm(metadata_list, desc="Getting Spotify IDs"):
        title = song.get("title", None)
        if not title:
            title = song.get("filename", None)
        artist = song.get("artist", None)
        album = song.get("album", None)

        if not title and not artist:
            continue

        # Search for song
        query = f"{title} {artist} {album}"
        results = sp_client.search(q=query, limit=1, type="track")

        # Get song ID
        if results["tracks"]["items"]:
            song_id = results["tracks"]["items"][0]["id"]

            # Skip song if its Spotify ID has been seen before
            if song_id in seen_spotify_ids:
                continue

            song["spotify_id"] = song_id

            # Get the artist's name and ID
            song["spotify_artist"] = results["tracks"]["items"][0]["artists"][0]["name"]
            song["spotify_artist_id"] = results["tracks"]["items"][0]["artists"][0]["id"]

            # Get the artist's genres
            artist_info = sp_client.artist(song["spotify_artist_id"])
            song["spotify_artist_genres"] = artist_info["genres"]

            # Add song to unique list and mark its Spotify ID as seen
            unique_metadata_list.append(song)
            seen_spotify_ids.add(song_id)

    return unique_metadata_list


def create_playlist(sp_client, playlist_name, metadata_list):
    # Create playlist
    playlist = sp_client.user_playlist_create(
        sp_client.me()["id"], playlist_name, public=False)

    # Add songs to playlist if not already in playlist
    song_ids = []
    for song in metadata_list:
        if song.get("spotify_id", None):
            song_ids.append(song["spotify_id"])

    # Add songs to playlist in batches of 20
    for i in tqdm(range(0, len(song_ids), 20), desc="Adding songs to playlist"):
        sp_client.user_playlist_add_tracks(
            sp_client.me()["id"], playlist["id"], song_ids[i:i+20])


def gen_chart_top_artist(metadata_list):
    artist_list = []
    for song in metadata_list:
        if song.get("spotify_artist", None):
            artist_list.append(song["spotify_artist"])

    artist_series = pd.Series(artist_list)
    top_artists = artist_series.value_counts().head(10)
    top_artists.plot.barh()
    plt.title("Top Artists")
    plt.xlabel("Number of Songs")
    plt.ylabel("Artist")
    plt.tight_layout()
    plt.savefig("top_artists.png")


def gen_chart_top_genre(metadata_list):
    genre_list = []
    for song in metadata_list:
        if song.get("spotify_artist_genres", None):
            genre_list.extend(song["spotify_artist_genres"])

    genre_series = pd.Series(genre_list)
    top_genres = genre_series.value_counts().head(10)
    top_genres.plot.barh()
    plt.title("Top Genres")
    plt.xlabel("Number of Songs")
    plt.ylabel("Genre")
    plt.tight_layout()
    plt.savefig("top_genres.png")


def main():
    sp_oauth = SpotifyOAuth(client_id=CLIENT_ID, client_secret=CLIENT_SECRET,
                            redirect_uri=REDIRECT_URI, scope="playlist-modify-private")
    sp_client = spotipy.Spotify(auth_manager=sp_oauth)

    metadata_list = get_metadata()
    metadata_list = get_spotify_data(sp_client, metadata_list)

    songs_with_id = 0
    for song in metadata_list:
        if song.get("spotify_id", None):
            songs_with_id += 1

    print(f"Found {songs_with_id} songs with Spotify IDs")
    print(
        f"Found {len(metadata_list) - songs_with_id} songs without Spotify IDs")

    # Create playlist
    create_playlist(sp_client, PLAYLIST_NAME, metadata_list)

    # Charts
    gen_chart_top_artist(metadata_list)
    gen_chart_top_genre(metadata_list)


if __name__ == "__main__":
    main()
