"""
YouTube Fallback Handler - Intelligent fallback system
"""
import asyncio
import random
from typing import Optional, Dict, Any, List
import config

class YouTubeFallbackHandler:
    def __init__(self):
        self.failed_videos = set()
        self.retry_count = {}
        self.last_success = 0
    
    async def should_use_youtube(self, video_id: str) -> bool:
        """Determine if we should try YouTube or skip to alternatives"""
        
        # If video failed recently, skip YouTube
        if video_id in self.failed_videos:
            return False
        
        # If too many recent failures, temporarily disable YouTube
        current_time = asyncio.get_event_loop().time()
        if current_time - self.last_success > 300:  # 5 minutes
            return False
        
        return True
    
    async def handle_youtube_failure(self, video_id: str, error: str, title: str = "") -> Optional[str]:
        """Handle YouTube failures intelligently"""
        
        self.failed_videos.add(video_id)
        
        if "Sign in to confirm" in error:
            print(f"🤖 Bot detected for {video_id}")
            
            # Try to find alternatives
            return await self.search_alternatives(title or video_id)
        
        return None
    
    async def search_alternatives(self, query: str) -> Optional[str]:
        """Search for alternatives in other platforms"""
        
        if not config.PLATFORM_FALLBACK_ORDER:
            return None
        
        print(f"🔍 Searching alternatives for: {query}")
        
        for platform in config.PLATFORM_FALLBACK_ORDER:
            if platform == "YouTube":
                continue
                
            try:
                # Try each platform
                if platform == "Spotify":
                    result = await self._search_spotify(query)
                elif platform == "SoundCloud":
                    result = await self._search_soundcloud(query)
                elif platform == "Apple":
                    result = await self._search_apple(query)
                
                if result:
                    print(f"✅ Found alternative on {platform}")
                    return result
                    
            except Exception as e:
                print(f"⚠️ {platform} search failed: {e}")
                continue
        
        return None
    
    async def _search_spotify(self, query: str) -> Optional[str]:
        """Search Spotify for alternative"""
        try:
            # This would integrate with existing Spotify search
            return f"spotify:track:{query}"  # Placeholder
        except:
            return None
    
    async def _search_soundcloud(self, query: str) -> Optional[str]:
        """Search SoundCloud for alternative"""
        try:
            # This would integrate with existing SoundCloud search
            return f"soundcloud:{query}"  # Placeholder
        except:
            return None
    
    async def _search_apple(self, query: str) -> Optional[str]:
        """Search Apple Music for alternative"""
        try:
            # This would integrate with existing Apple Music search
            return f"apple:{query}"  # Placeholder
        except:
            return None
    
    def mark_success(self, video_id: str):
        """Mark a successful YouTube operation"""
        self.last_success = asyncio.get_event_loop().time()
        if video_id in self.failed_videos:
            self.failed_videos.remove(video_id)

# Global instance
youtube_fallback = YouTubeFallbackHandler()
