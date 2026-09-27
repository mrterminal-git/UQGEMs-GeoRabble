#!/usr/bin/env python3
"""
Split large cache files into smaller chunks for better performance.
Each chunk is keyed by the first-level key (ward/hexagon ID).
"""

import json
import sys
from pathlib import Path
from typing import Dict, Any


def sanitize_filename(ward_id: str) -> str:
    """Sanitize ward/hexagon ID for use in filename."""
    return ward_id.replace(':', '_').replace('/', '_')


def split_cache_file(input_path: Path, output_dir: Path, max_chunk_size_kb: int = 500) -> None:
    """
    Split a cache file into smaller chunks.
    Cache structure: {region1_id: {region2_id: [routes]}}
    Combines multiple regions into chunks up to max_chunk_size_kb.
    """
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")
    
    print(f"Loading {input_path}...")
    with open(input_path, 'r') as f:
        cache_data: Dict[str, Dict[str, Any]] = json.load(f)
    
    output_dir.mkdir(parents=True, exist_ok=True)

    # Clear stale chunks from previous runs so orphans don't accumulate
    for old_chunk in output_dir.glob('chunk_*.json'):
        old_chunk.unlink()
    old_index = output_dir / 'index.json'
    if old_index.exists():
        old_index.unlink()

    max_chunk_size_bytes = max_chunk_size_kb * 1024
    index: Dict[str, str] = {}
    total_size = 0
    chunk_count = 0
    current_chunk: Dict[str, Dict[str, Any]] = {}
    current_chunk_size = 0
    
    def write_chunk(chunk_data: Dict[str, Dict[str, Any]], chunk_num: int) -> str:
        """Write a chunk to disk and return the filename."""
        chunk_filename = f"chunk_{chunk_num:04d}.json"
        chunk_path = output_dir / chunk_filename
        
        with open(chunk_path, 'w') as f:
            json.dump(chunk_data, f, separators=(',', ':'))
        
        return chunk_filename
    
    for region_id, connections in cache_data.items():
        # Estimate size of this region's data
        test_chunk = {region_id: connections}
        test_json = json.dumps(test_chunk, separators=(',', ':'))
        region_size = len(test_json.encode('utf-8'))
        
        # If adding this region would exceed the limit, write current chunk first
        if current_chunk_size > 0 and current_chunk_size + region_size > max_chunk_size_bytes:
            chunk_filename = write_chunk(current_chunk, chunk_count)
            chunk_size = (output_dir / chunk_filename).stat().st_size
            total_size += chunk_size
            
            # Update index for all regions in this chunk
            for rid in current_chunk.keys():
                index[rid] = chunk_filename
            
            chunk_count += 1
            current_chunk = {}
            current_chunk_size = 0
            
            if chunk_count % 10 == 0:
                print(f"Processed {chunk_count} chunks...")
        
        # Add region to current chunk
        current_chunk[region_id] = connections
        current_chunk_size += region_size
    
    # Write final chunk if it has data
    if current_chunk:
        chunk_filename = write_chunk(current_chunk, chunk_count)
        chunk_size = (output_dir / chunk_filename).stat().st_size
        total_size += chunk_size
        
        for rid in current_chunk.keys():
            index[rid] = chunk_filename
        
        chunk_count += 1
    
    # Write index file
    index_path = output_dir / 'index.json'
    with open(index_path, 'w') as f:
        json.dump(index, f, separators=(',', ':'))
    
    avg_size_kb = (total_size / chunk_count / 1024) if chunk_count > 0 else 0
    print(f"\nSplit complete!")
    print(f"  Total chunks: {chunk_count}")
    print(f"  Total size: {total_size / (1024*1024):.2f} MB")
    print(f"  Average chunk size: {avg_size_kb:.2f} KB")
    print(f"  Max chunk size: {max_chunk_size_kb} KB")
    print(f"  Index file: {index_path}")
    print(f"  Output directory: {output_dir}")


def main():
    """Main entry point."""
    if len(sys.argv) < 3:
        print("Usage: python split_cache_files.py <input_file> <output_dir>")
        print("Example: python split_cache_files.py static/data/routes_cache.json static/data/routes_cache_chunks")
        sys.exit(1)
    
    input_path = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])
    
    try:
        split_cache_file(input_path, output_dir)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
