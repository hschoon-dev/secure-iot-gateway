import tracemalloc

def format_size(num_bytes: int) -> str:
    """ Formats the amount of bytes to a human-readable string """
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(num_bytes) < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} PiB"

# These two snapshots were captured
# Snapshot one is the memory shortly after program start
# Snapshot two is the memory after running the fuzzer and growing the usage to ~500MB
snapshot1 = tracemalloc.Snapshot.load("interface-partition/snapshot1.tracemalloc")
snapshot2 = tracemalloc.Snapshot.load("interface-partition/snapshot2.tracemalloc")
print(f"Loaded snapshot1: size={format_size(sum(s.size for s in snapshot1.statistics("filename", cumulative=True)))}")
print(f"Loaded snapshot2: size={format_size(sum(s.size for s in snapshot2.statistics("filename", cumulative=True)))}")

# Compare on memory allocations per line of code and sort by total usage
diff_stats = snapshot2.compare_to(snapshot1, key_type="lineno")
stats = sorted(diff_stats, key=lambda s: s.size, reverse=True)

# Print the 10 highest usage lines
for stat in stats[:10]:
    print(
        # Filename
        f"{stat.traceback.format()[0]} "
        # Difference of total size of memory blocks in bytes between the old and the new snapshots (int): 
        # 0 if the memory blocks have been allocated in the new snapshot.
        f"size_diff={format_size(stat.size_diff)}, "
        # Total size of memory blocks in bytes in the new snapshot (int): 
        # 0 if the memory blocks have been released in the new snapshot.
        f"new_total={format_size(stat.size)}, "
        # Difference of number of memory blocks between the old and the new snapshots (int): 
        # 0 if the memory blocks have been allocated in the new snapshot.
        f"count_diff={stat.count_diff}\n",
        # Respective line of code
        "".join(line for line in stat.traceback.format()[1:])
    )