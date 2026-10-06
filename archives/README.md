# Original Massive version

Original upstream repository: https://github.com/yuz047/greenlight-trader

- Original latest main: `85199fbf2d8e39b600880977185e4c7c87d7ce0b`.
- Explicit trusted portfolio recovery baseline: `164c8a307449d6ce63e7f70bb829515b4c5eae31`.
- The original downloaded project remains in its parent folder, alongside `yfinance_version` and the earlier diagnostic folder. It was not overwritten or deleted.

The local archive contains a ZIP of the original upstream main and a separate ZIP of the original downloaded project, preserving differences between them. Credentials, virtual environments, caches, and migration/diagnostic folders are excluded. Archive hashes and file manifests are kept locally; ZIPs are gitignored and are not included in the source upload.

To inspect or restore the upstream source in another folder:

```text
git clone https://github.com/yuz047/greenlight-trader greenlight-massive-original
git -C greenlight-massive-original checkout 85199fbf2d8e39b600880977185e4c7c87d7ce0b
```

Restoration does not imply running the old scheduled workflow or changing the live deployment. The migration source does not modify the original main branch.
