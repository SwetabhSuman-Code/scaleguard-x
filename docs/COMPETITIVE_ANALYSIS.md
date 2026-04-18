# Competitive Analysis

The repository now includes a helper script at `benchmarks/competitive_analysis.py` that renders an honest comparison table using local benchmark artifacts plus placeholders for external-tool measurements.

Current guidance:

- treat the ScaleGuard column as measured only where JSON benchmark artifacts exist
- treat Kubernetes HPA and Datadog columns as pending until you run equivalent tests in matching environments
- do not publish exact external numbers unless they were gathered under the same workload profile

To generate the markdown table:

```bash
python benchmarks/competitive_analysis.py
```
