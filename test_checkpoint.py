"""
OSINT Agent - Checkpoint/Resume Test
====================================

Amaç: Yeni özellikleri test etmek
- checkpoint kaydı
- --resume ile devam
- Rate limiting logs
- File logging
"""

import os
import sys
from osint_agents import run_research, logger

if __name__ == "__main__":
    logger.info("=" * 70)
    logger.info("CHECKPOINT/RESUME TEST")
    logger.info("=" * 70)
    
    query = "Guido van Rossum"
    
    # Test 1: Baştan başla
    print("\n▶️  Test 1: İlk çalıştırma (derinlik=1, 5 saniye sonra Ctrl+C yapacağız)")
    print("Ctrl+C yaparsanız checkpoint kaydedilip çıkacak...")
    print()
    
    try:
        kg = run_research(query, max_depth=1, resume=False)
        logger.info(f"✅ Tamamlandı: {len(kg.nodes)} düğüm, {len(kg.edges)} kenar")
        
    except KeyboardInterrupt:
        logger.info("⏸️  Kesinti - checkpoint kaydedildi")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Hata: {e}")
        sys.exit(1)
