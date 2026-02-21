

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import Settings


def download_model():
    
    project_root = Path(__file__).parent.parent
    embedding_cache = project_root / "embedding_model"
    embedding_cache.mkdir(exist_ok=True)
    
    print(f"📦 Embedding model cache directory: {embedding_cache}")
    
    os.environ["HF_HOME"] = str(embedding_cache)
    os.environ["TRANSFORMERS_CACHE"] = str(embedding_cache)
    os.environ["SENTENCE_TRANSFORMERS_HOME"] = str(embedding_cache)
    
    os.environ.pop("HF_HUB_OFFLINE", None)
    os.environ.pop("TRANSFORMERS_OFFLINE", None)
    os.environ.pop("HF_DATASETS_OFFLINE", None)
    
    settings = Settings()
    model_name = settings.MEM0_EMBEDDING_MODEL
    
    print(f"🚀 Starting download of model: {model_name}")
    print("⏳ This may take a few minutes depending on your internet connection...")
    print()
    
    try:
        from sentence_transformers import SentenceTransformer
        
        print(f"⬇️  Downloading {model_name}...")
        model = SentenceTransformer(
            model_name,
            cache_folder=str(embedding_cache),
            device="cpu"
        )
        
        print("✅ Model downloaded successfully!")
        print()
        
        print("🧪 Testing model with a sample embedding...")
        test_text = "This is a test sentence for embedding."
        embedding = model.encode(test_text)
        
        print(f"✅ Model test successful!")
        print(f"   - Embedding shape: {embedding.shape}")
        print(f"   - Embedding dimensions: {len(embedding)}")
        print()
        
        print("📁 Verifying cached files...")
        possible_locations = [
            embedding_cache / "models--BAAI--bge-m3",
            embedding_cache / "sentence-transformers_BAAI_bge-m3",
            embedding_cache / "BAAI_bge-m3",
        ]
        
        found = False
        for location in possible_locations:
            if location.exists():
                print(f"   ✓ Found model at: {location}")
                found = True
                files = list(location.rglob("*"))[:5]
                if files:
                    print(f"   ✓ Contains {len(list(location.rglob('*')))} files")
        
        if not found:
            print("   ⚠️  Warning: Model cache location not in expected format")
            print(f"   ℹ️  Check contents of: {embedding_cache}")
        
        print()
        print("=" * 60)
        print("✨ SUCCESS! The embedding model is now ready for offline use.")
        print("=" * 60)
        print()
        print("The application will now automatically use the local model")
        print("without requiring an internet connection.")
        print()
        
        return 0
        
    except ImportError as e:
        print(f"❌ Error: Required package not found: {e}")
        print("   Please install required packages:")
        print("   pip install sentence-transformers")
        return 1
        
    except Exception as e:
        print(f"❌ Error downloading model: {e}")
        print()
        print("Troubleshooting:")
        print("1. Check your internet connection")
        print("2. Verify you have enough disk space (~2GB needed)")
        print("3. Check if you can access huggingface.co")
        print("4. Try running with verbose logging:")
        print("   HF_HUB_VERBOSITY=debug python scripts/load_embedding_model.py")
        return 1


if __name__ == "__main__":
    sys.exit(download_model())

