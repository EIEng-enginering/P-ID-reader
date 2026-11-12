"""Runtime provenance and process peak memory, separate from recognition accuracy."""
import importlib.metadata
import platform
import sys

def metadata():
    versions={}
    for name in ('torch','torchvision','easyocr','transformers','rfdetr','Pillow'):
        try:versions[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:versions[name]=None
    peak=None
    try:
        import resource
        peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        peak=peak/(1024*1024) if sys.platform=='darwin' else peak/1024
    except ImportError:pass
    if peak is None:
        try:
            import psutil
            info=psutil.Process().memory_info()
            # Windows keeps a true process high-water mark; other platforms without `resource` fall back to current RSS.
            peak=getattr(info,'peak_wset',info.rss)/(1024*1024)
        except Exception:pass
    return dict(python=platform.python_version(),platform=platform.platform(),versions=versions,worker_module_file=__file__,
                peak_worker_rss_mib=peak,peak_memory_scope='Worker process high-water mark (ru_maxrss on Linux/macOS, peak working set via psutil on Windows)')
