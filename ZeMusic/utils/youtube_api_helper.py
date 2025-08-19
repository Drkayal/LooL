"""
YouTube Data API Helper - Standalone module for API integration
"""
import aiohttp
import re
import asyncio
from typing import Optional, Dict, Any, List

class YouTubeAPIHelper:
    """YouTube Data API helper for getting video information"""
    
    def __init__(self):
        # API Keys
        self.api_keys = [
            "AIzaSyA3x5N5DNYzd5j7L7JMn9XsUYil32Ak77U",
            "AIzaSyDw09GqGziUHXZ3FjugOypSXD7tedWzIzQ"
        ]
        self.current_key_index = 0
        self.api_base = "https://www.googleapis.com/youtube/v3"
        self.enabled = True
    
    def get_current_api_key(self) -> Optional[str]:
        """Get current API key"""
        if not self.api_keys:
            return None
        return self.api_keys[self.current_key_index]
    
    def rotate_api_key(self):
        """Rotate to next API key"""
        if len(self.api_keys) > 1:
            self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
            print(f"🔄 Rotated to API key {self.current_key_index + 1}")
    
    def extract_video_id(self, url: str) -> Optional[str]:
        """Extract video ID from YouTube URL"""
        patterns = [
            r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([^&\n?#]+)',
            r'youtube\.com/v/([^&\n?#]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None
    
    async def get_video_info(self, video_id: str, max_retries: int = 2) -> Optional[Dict[str, Any]]:
        """Get video info using YouTube Data API"""
        if not self.enabled or not self.api_keys:
            return None
        
        for attempt in range(max_retries):
            try:
                api_key = self.get_current_api_key()
                if not api_key:
                    return None
                
                url = f"{self.api_base}/videos"
                params = {
                    'part': 'snippet,contentDetails,statistics',
                    'id': video_id,
                    'key': api_key
                }
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, params=params) as response:
                        if response.status == 200:
                            data = await response.json()
                            if data.get('items'):
                                item = data['items'][0]
                                
                                # Parse duration
                                duration_str = item['contentDetails']['duration']
                                duration = self._parse_duration(duration_str)
                                
                                return {
                                    'id': video_id,
                                    'title': item['snippet']['title'],
                                    'description': item['snippet'].get('description', ''),
                                    'duration': duration,
                                    'view_count': int(item['statistics'].get('viewCount', 0)),
                                    'like_count': int(item['statistics'].get('likeCount', 0)),
                                    'channel': item['snippet']['channelTitle'],
                                    'published': item['snippet']['publishedAt'],
                                    'thumbnail': item['snippet']['thumbnails']['high']['url'],
                                    'api_source': True,
                                    'url': f"https://www.youtube.com/watch?v={video_id}"
                                }
                        elif response.status == 403:
                            print(f"🔑 API key quota exceeded, rotating...")
                            self.rotate_api_key()
                            if attempt < max_retries - 1:
                                continue
                        else:
                            print(f"❌ API request failed: {response.status}")
                            return None
            except Exception as e:
                print(f"❌ API request error: {e}")
                if attempt < max_retries - 1:
                    self.rotate_api_key()
                    continue
        
        return None
    
    def _parse_duration(self, duration_str: str) -> int:
        """Parse ISO 8601 duration to seconds"""
        match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration_str)
        if not match:
            return 0
        
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)
        
        return hours * 3600 + minutes * 60 + seconds
    
    async def search_videos(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """Search for videos using YouTube Data API"""
        if not self.enabled or not self.api_keys:
            return []
        
        try:
            api_key = self.get_current_api_key()
            if not api_key:
                return []
            
            url = f"{self.api_base}/search"
            params = {
                'part': 'snippet',
                'q': query,
                'type': 'video',
                'maxResults': max_results,
                'key': api_key
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        results = []
                        
                        for item in data.get('items', []):
                            video_id = item['id']['videoId']
                            results.append({
                                'id': video_id,
                                'title': item['snippet']['title'],
                                'channel': item['snippet']['channelTitle'],
                                'published': item['snippet']['publishedAt'],
                                'thumbnail': item['snippet']['thumbnails']['high']['url'],
                                'url': f"https://www.youtube.com/watch?v={video_id}",
                                'description': item['snippet']['description']
                            })
                        
                        return results
                    elif response.status == 403:
                        self.rotate_api_key()
                        return []
        except Exception as e:
            print(f"❌ Search API error: {e}")
            return []
        
        return []

# Global instance
youtube_api_helper = YouTubeAPIHelper()

# Convenience functions
async def get_youtube_info(url: str) -> Optional[Dict[str, Any]]:
    """Get YouTube video info from URL"""
    video_id = youtube_api_helper.extract_video_id(url)
    if video_id:
        return await youtube_api_helper.get_video_info(video_id)
    return None

async def search_youtube(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """Search YouTube videos"""
    return await youtube_api_helper.search_videos(query, max_results)

async def is_youtube_url(url: str) -> bool:
    """Check if URL is a YouTube URL"""
    return youtube_api_helper.extract_video_id(url) is not None