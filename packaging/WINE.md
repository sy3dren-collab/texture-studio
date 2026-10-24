# Wine 建置紀錄

原生 Windows 建置仍是首選：執行 `build_windows.bat` 或 GitHub Windows 工作流程。本次 GitHub API 受雲端網域白名單限制，未取得遠端 Windows 執行證據，改用下列相容環境產生單檔 PE。

- 固定映像：`tobix/pywine@sha256:65dd1d8c0f3b4b951e49e9caababf12f497b02c45a883bd18c731e8eb9c2f9c0`。
- 使用 `/opt/wine-devel/bin/wine64` 執行 Windows CPython 3.12.7；本環境不支援映像內預設的 32-bit Wine loader。
- 以 Xvfb 提供畫面，`DISPLAY=:99`；`LANG=C.UTF-8`、`LC_ALL=C.UTF-8` 讓相容層支援中文路徑。
- 固定套件來自 `requirements-dev.txt`，另備妥 Windows 的 `pefile==2023.2.7`、`pywin32-ctypes==0.2.3`、`colorama==0.4.6`。透過正常 TLS 驗證下載 Windows x64 wheels，再於停用網路的容器內離線安裝。
- Wine 內建 UCRT 缺少 NumPy 所需的 `crealf`。使用官方 [Microsoft.Windows.SDK.CPP 10.0.19041.5](https://api.nuget.org/v3-flatcontainer/microsoft.windows.sdk.cpp/10.0.19041.5/microsoft.windows.sdk.cpp.10.0.19041.5.nupkg) 內 `c/Redist/10.0.19041.0/ucrt/DLLs/x64/ucrtbase.dll`，只補充建置容器的系統 DLL，並設定 `WINEDLLOVERRIDES=ucrtbase=n,b`。下載的 SDK SHA-256 為 `35074cafacc99a47e87c25641f98e0952576487fe29607103f83d61540ad0523`。
- 在 Windows 虛擬環境執行 `python.exe packaging/build_windows.py --output Z:/work/final --allow-wine`；所有測試、PE 檢查與隔離啟動仍須通過，報告保留 Wine 標記。

成品不包含 Wine、此建置容器或外部 Python。驗證時已移除外部 Python 路徑、只保留系統 PATH，使用內含的 Python／Qt／影像套件執行；Windows 10／11 系統本身提供 UCRT。

這是相容環境的實際執行結果，不等同原生 Windows 實機驗證。`tests/test_windows_entry.py` 僅在原生 Windows 檢查 VBS／Script Host；獨立 EXE 本身不依賴 VBS。
