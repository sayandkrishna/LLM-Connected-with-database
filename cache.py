import redis
import hashlib
import time
import numpy as np
from typing import Dict, Any, Optional
from sklearn.metrics.pairwise import cosine_similarity
from models import SemanticCacheEntry
from config import settings

class CacheManager:
    """Manages Redis caching operations and semantic caching."""
    
    def __init__(self):
        self.client = None
        self.embedding_model = None
        self._setup_redis()
        self._setup_embedding_model()
    
    def _setup_redis(self):
        """Setup Redis connection."""
        try:
            self.client = redis.Redis(
                host=settings.REDIS_HOST, 
                port=settings.REDIS_PORT, 
                db=settings.REDIS_DB, 
                decode_responses=True
            )
            self.client.ping()
            print("✅ Successfully connected to Redis.")
        except redis.exceptions.ConnectionError as e:
            print(f"⚠️ Could not connect to Redis: {e}. Caching will be disabled.")
            self.client = None
    
    def _setup_embedding_model(self):
        """Setup the sentence transformer model for embeddings."""
        try:
            from sentence_transformers import SentenceTransformer
            print("🔄 Loading sentence transformer model...")
            self.embedding_model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
            print("✅ Embedding model loaded successfully.")
        except Exception as e:
            print(f"⚠️ Failed to load embedding model: {e}")
            self.embedding_model = None
    
    def get_query_embedding(self, query: str) -> Optional[np.ndarray]:
        """Generate embedding for a query using the sentence transformer model."""
        if not self.embedding_model:
            return None
        try:
            embedding = self.embedding_model.encode([query.lower().strip()])[0]
            return embedding
        except Exception as e:
            print(f"Error generating embedding: {e}")
            return None
    
    def store_semantic_cache(self, user_id: str, query: str, embedding: np.ndarray, response: Dict[str, Any]):
        """Store query-response pair with embedding in Redis."""
        if not self.client:
            return
        
        try:
            cache_entry = SemanticCacheEntry(
                query=query,
                embedding=embedding.tolist(),
                response=response,
                timestamp=time.time(),
                user_id=user_id
            )
            
            # Store with a unique key
            cache_key = f"semantic_cache:{user_id}:{hashlib.sha256(query.encode()).hexdigest()[:16]}"
            self.client.setex(
                cache_key, 
                settings.CACHE_EXPIRATION_SECONDS, 
                cache_entry.json()
            )
            
            # Also add to a user's cache index for retrieval
            index_key = f"semantic_index:{user_id}"
            self.client.sadd(index_key, cache_key)
            self.client.expire(index_key, settings.CACHE_EXPIRATION_SECONDS)
            
            print(f"✅ Stored semantic cache entry: {cache_key}")
        except Exception as e:
            print(f"Error storing semantic cache: {e}")
    
    def find_similar_cached_query(self, user_id: str, query: str, query_embedding: np.ndarray) -> Optional[Dict[str, Any]]:
        """Find semantically similar cached queries using vector similarity."""
        if not self.client:
            return None
            
        try:
            index_key = f"semantic_index:{user_id}"
            cached_keys = self.client.smembers(index_key)
            
            if not cached_keys:
                return None
            
            best_match = None
            best_similarity = 0
            
            for cache_key in cached_keys:
                try:
                    cached_data = self.client.get(cache_key)
                    if not cached_data:
                        continue
                        
                    cache_entry = SemanticCacheEntry.parse_raw(cached_data)
                    cached_embedding = np.array(cache_entry.embedding).reshape(1, -1)
                    current_embedding = query_embedding.reshape(1, -1)
                    
                    similarity = cosine_similarity(current_embedding, cached_embedding)[0][0]
                    
                    if similarity > best_similarity and similarity > settings.SEMANTIC_SIMILARITY_THRESHOLD:
                        best_similarity = similarity
                        best_match = {
                            "response": cache_entry.response,
                            "similarity": similarity,
                            "original_query": cache_entry.query,
                            "cache_key": cache_key
                        }
                        
                except Exception as e:
                    print(f"Error processing cached entry {cache_key}: {e}")
                    continue
            
            if best_match:
                print(f"🎯 Found similar query (similarity: {best_match['similarity']:.3f})")
                print(f"   Original: {best_match['original_query']}")
                print(f"   Current:  {query}")
                
                # Update hit count
                try:
                    cached_data = self.client.get(best_match['cache_key'])
                    cache_entry = SemanticCacheEntry.parse_raw(cached_data)
                    cache_entry.hit_count += 1
                    self.client.setex(
                        best_match['cache_key'], 
                        settings.CACHE_EXPIRATION_SECONDS, 
                        cache_entry.json()
                    )
                except:
                    pass
                    
            return best_match
            
        except Exception as e:
            print(f"Error finding similar cached query: {e}")
            return None
    
    def get_cache_stats(self, user_id: str) -> Dict[str, Any]:
        """Get semantic cache statistics for a specific user."""
        if not self.client:
            return {"error": "Cache not available"}
        
        try:
            index_key = f"semantic_index:{user_id}"
            cached_keys = self.client.smembers(index_key)
            
            stats = {
                "total_cached_queries": len(cached_keys),
                "cache_entries": []
            }
            
            for cache_key in cached_keys:
                try:
                    cached_data = self.client.get(cache_key)
                    if cached_data:
                        cache_entry = SemanticCacheEntry.parse_raw(cached_data)
                        stats["cache_entries"].append({
                            "query": cache_entry.query,
                            "hit_count": cache_entry.hit_count,
                            "timestamp": cache_entry.timestamp,
                            "response_type": cache_entry.response.get("action", "query")
                        })
                except Exception as e:
                    print(f"Error reading cache entry {cache_key}: {e}")
                    continue
            
            # Sort by hit count descending
            stats["cache_entries"].sort(key=lambda x: x["hit_count"], reverse=True)
            
            return stats
        except Exception as e:
            print(f"Error getting cache stats: {e}")
            return {"error": "Failed to retrieve cache statistics"}
    
    def clear_user_cache(self, user_id: str) -> Dict[str, Any]:
        """Clear all cached queries for a specific user."""
        if not self.client:
            return {"error": "Cache not available"}
        
        try:
            index_key = f"semantic_index:{user_id}"
            cached_keys = self.client.smembers(index_key)
            
            # Delete all cache entries
            if cached_keys:
                self.client.delete(*cached_keys)
            
            # Delete the index
            self.client.delete(index_key)
            
            return {
                "message": f"Cleared {len(cached_keys)} cached queries",
                "cleared_count": len(cached_keys)
            }
        except Exception as e:
            print(f"Error clearing cache: {e}")
            return {"error": "Failed to clear cache"}

# Global cache manager instance
cache_manager = CacheManager()
