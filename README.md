# Texture Studio

繁體中文、本機運算的無縫貼圖與板材生成器。Python 3.11+、PySide6、OpenCV、NumPy、Pillow；無須外部 API、帳號或 API Key。

目前為可執行初版，不代表規格書 v1.0 全部完成驗收。核心演算法獨立於 UI，計算與圖片讀寫使用背景工作執行緒。取消在演算法步驟與板片之間生效，單次 FFT／解碼不能立即中斷。

## Windows 10／11

先將 ZIP **完整解壓縮**到一般資料夾，不可在壓縮檔檢視器內直接執行。安裝 64-bit Python 3.12（3.11–3.13 也支援，包含 Python Launcher），執行：

```bat
setup_windows.bat
start_windows.bat
build_windows.bat
```

Windows 腳本會將環境安裝至 `%USERPROFILE%\.texture-studio\venv`，避免 ZIP 解壓縮目錄過長，導致 PySide6 安裝失敗。不需系統管理員權限或修改 Windows 長路徑登錄設定。三支腳本共用 `windows_env.bat`；也可設定 `TEXTURE_STUDIO_VENV` 使用自訂短路徑。先前安裝失敗的專案內 `.venv` 不會被刪除或沿用。

打包結果為 `%USERPROFILE%\.texture-studio\packaging\dist\TextureStudio\TextureStudio.exe`，需分發**整個 TextureStudio 資料夾**。目標電腦不需 Python。打包必須在 Windows 執行；Linux 無法藉此產生 Windows EXE。本次沒有產生或驗證 Windows EXE。

本版固定依賴支援 Python 3.11–3.13；Python 3.14 目前不支援。也可手動建立環境：

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m texture_studio
```

Linux 伺服器測試設定 `QT_QPA_PLATFORM=offscreen`。離屏模式不提供可互動桌面，實際操作需有圖形顯示環境。

### 啟動失敗或視窗閃退

先執行 `setup_windows.bat`，確認出現 `Setup completed`；再執行 `start_windows.bat`。修正版啟動腳本會在錯誤時保留視窗，安裝及啟動紀錄分別位於 `logs/setup.log`、`logs/startup-console.log`，Python 啟動例外另存 `logs/texture-studio.log`。請提供錯誤文字以診斷，不需重裝所有套件猜測原因。

若短路徑環境使用不支援的 Python，先將 `%USERPROFILE%\.texture-studio\venv` 改名保留，安裝 64-bit Python 3.12，再重跑安裝腳本。腳本不會自動刪除既有環境。Windows 批次腳本仍須在 Windows 實機驗證；Linux 測試不能證明 Windows 安裝成功。

若使用舊 ZIP 遇到 Long Path 安裝錯誤，可在包含 `requirements.txt` 與 `launch.py` 的資料夾依序執行，不需重新下載：

```bat
py -3.12 -m venv "%USERPROFILE%\.texture-studio\venv"
"%USERPROFILE%\.texture-studio\venv\Scripts\python.exe" -m pip install -r requirements.txt
"%USERPROFILE%\.texture-studio\venv\Scripts\python.exe" launch.py
```

每一步成功後才進行下一步。`No module named cv2` 可能是前面套件安裝中斷造成，請先解決安裝錯誤。以上手動流程與新版啟動腳本使用相同短路徑，舊版 `start_windows.bat` 仍指向專案內 `.venv`，請使用上面的啟動命令或更新腳本。

## 快速製圖（v0.4）

1. 按「匯入圖片」，或使用它上方的「截圖匯入素材」。截圖時程式會暫時隱藏，拖曳框選螢幕範圍後自動加入素材；Esc 或右鍵取消。多螢幕各自顯示選取畫面，一次選取單一螢幕內的範圍，依該螢幕的像素密度擷取。截圖素材暫存於本次程式工作階段，關閉程式會清理暫存檔。
2. 如需取用素材的一部分，按「框選製圖範圍」。在原圖拖曳框選，框內拖曳移動、四角調整大小；「恢復整張」取消框選。每張素材各自記住本次使用的範圍，不修改原始檔。
3. 選模式，按「一鍵製圖」。飽和度、明暗、上色、縮放與角度調整會自動更新預覽。
4. 用 1／2／3／4／5 重複預覽檢查接縫。「全屏」將貼圖連續鋪滿上方檢視區，可拖曳平移、滾輪縮放；「返回預覽」恢復一般檢視。這是檢視區鋪滿功能，不切換作業系統全螢幕，也不改變儲存圖片的尺寸。框選範圍時暫時顯示單張原圖。
5. 按匯入圖片下方的「儲存檔案」。原始檔存在時會詢問「是否覆蓋原檔案？」：選「覆蓋原檔」保留原檔格式，選「另存 JPEG」開啟另存視窗，或按「取消」。截圖素材、原檔已不存在或原格式無法寫入時，直接開啟 JPEG 另存視窗。

儲存會依目前設定重新計算完整解析度，不會拿小尺寸預覽圖代替。JPEG 採 quality 95、4:4:4 色彩取樣與 sRGB profile。覆蓋支援 JPEG／PNG／TIFF／BMP；先在同目錄完成圖片寫入與解碼檢查，再替換原檔。若運算期間原檔在外部變更，會停止覆蓋並顯示錯誤。

調整與預覽不修改來源，只有確認「覆蓋原檔」才會寫入。覆蓋後，本次工作階段仍保留匯入時的素材供繼續調整，避免重複套用明暗或縮放；移除並重新匯入會讀取已儲存的新檔。「回到上次結果」只還原程式內的結果，若要更新磁碟檔案，需再次儲存。覆蓋使用 RGB 8-bit 工作流程，不保留多頁 TIFF、原始 EXIF 或其他來源中繼資料。

去暗角下方依序提供：

| 控制 | 用途 |
| --- | --- |
| 飽和度 | 0–200%，100% 原始飽和度，0% 灰階 |
| 明暗度 | −100–100%，0% 原始明暗，向右變亮、向左變暗 |
| 上色／恢復原色 | 開啟顏色視窗，用選定顏色取代原色並保留紋理明暗；恢復原色會清除上色，保留其他滑桿設定 |
| 素材縮放 | 25–400%，100% 原始大小；200% 讓紋路放大兩倍，輸出像素尺寸保持不變 |
| 旋轉角度 | −180–180°，繞單張素材中心旋轉；木地板先處理每張素材，再組合排列，板縫與地板排列不隨紋路旋轉 |

滑鼠在飽和度、明暗度、素材縮放、旋轉角度、變化程度的滑桿上按右鍵，會分別恢復 100%、0%、100%、0°、20% 的預設值。

圖形介面已移除「輸出 JPEG 圖片」「輸出全部」「儲存專案」「開啟專案」「原圖比較」「接縫線」「查看結果」。儲存統一使用「儲存檔案」；隨機模式一次顯示一張結果，按「換一組」更換。命令列的進階批次／JSON 記錄不受桌面介面簡化影響。

| 模式 | 其他主要調整 |
| --- | --- |
| 無縫貼圖 | 去暗角／陰影、輸出大小 |
| 隨機變體 | 去暗角／陰影、變化程度、保留木紋方向、輸出大小 |
| 木地板 | 去暗角／陰影、排列方式、板寬、板長、板縫、輸出大小 |

其他數值自動計算。隨機模式按「換一組」換結果。拖曳控制時使用最長邊 1024 的背景預覽並合併連續變更；輸出會重新計算完整解析度，等待中的預覽不會覆蓋最新設定。去陰影／來源無變更時重用預處理素材，避免每次拉滑桿都重算大圖光照。可用「回到上次結果」還原上一次影像與調整設定。

「自動」使用選取範圍的解析度；木地板自動輸出為 1K。1K–8K 指長邊，短邊依比例計算，不強制拉伸成正方形。木地板預設整面為四片板長 × 十二列板寬，自動符合直鋪、固定錯縫與隨機錯縫的週期。

去暗角預設 85%，0 為停用，使用穩健光照曲面與紋理保護濾波。天然深色紋路與光照無法從單張 RGB 完美區分，仍應目視檢查；可框選排除照片過暗、遮擋或背景區域。縮小／旋轉以週期取樣處理空白區，並重建輸出邊界，不會增加黑角。

圖片依 EXIF 校正方向，有 ICC 時轉換為 sRGB；目前使用 RGB 8-bit 工作流程。木地板素材以保留比例的中心裁切符合板片，不直接拉伸。板縫寬設為 0 可輸出無板縫版本；Base Color 不加入假倒角光影。

## 命令列與架構

```sh
python -m texture_studio.cli tile 木紋.jpg --output output/tile --maps
python -m texture_studio.cli variants 木紋.jpg --output output/variants --count 8 --seed 42
python -m texture_studio.cli boards 板1.png 板2.png --config boards.json --output output/floor --maps
```

CLI 拒絕覆寫既有輸出。`boards.json` 是 `BoardSettings` 欄位物件，例如：

```json
{
  "width": 4096, "height": 2048,
  "world_width_mm": 3600, "world_height_mm": 1800,
  "board_width_mm": 150, "board_length_mm": 900,
  "pattern": "random", "gap_mm": 2, "periodic": true,
  "weights": [1, 2]
}
```

- `core.py`：讀寫、色彩管理、低頻光照估計、週期性 Poisson 分解、接縫量測。
- `variants.py`：可重現變體、週期取樣旋轉。
- `boards.py`：物理尺寸拼板、週期排列、板縫與倒角參考。
- `maps.py`：高度、粗糙度、OpenGL +Y 法線推估。
- `storage.py`：確認覆蓋後的暫存寫入、檔案變更檢查與原檔替換。
- `ui.py`：介面與工作執行緒；`cli.py`：無 GUI 批次處理。

## 色彩與影像處理限制

Base Color 附 sRGB profile；Mask／Height／Roughness／Normal 不附 sRGB profile，在 Corona／3ds Max 中應設定 linear／non-color。Normal 需配合材質的法線方向設定。高度、粗糙度、法線僅為 RGB 推估，不能恢復量測的反射率或幾何。

週期性 Poisson 分解移除造成邊界跳變的平滑分量，不在中央做交叉羽化；但不是高階內容感知合成，也不保證所有天然紋理無可見重複。明暗與材質固有深色無法單從 RGB 完美區分，務必目視檢查。首末像素是相隔一個取樣點的相鄰像素，差值通常不是零。

## 驗證與尚待完成的驗收

執行 `python -m pytest -q`。測試包含合成木紋／石材／布料、細節保留、明暗漸層、中文檔名、Seed、任意旋轉、標準／特殊排列、拒絕不相容週期、法線向量、真實圖片讀寫、Qt 主執行緒更新、背景處理、框選／移動／調整大小、截圖像素密度、飽和度／明暗／上色、中心縮放／旋轉、完整 JPEG 儲存、復原、確認／取消覆蓋、缺少來源時另存、重複儲存不累加效果、覆蓋失敗保留原檔、四格預覽、鋪滿平移與右鍵重設。

尚未完成整份規格的產品驗收：

- 真實素材人工品質驗收、Windows 10／11 操作、EXE 啟動及 3ds Max／Corona 實測。
- 素材旋轉校正、排序／完整縮圖管理、局部板片替換與互動自訂排法。
- 嚴格跨列最短錯縫、上下相鄰素材去重、禁止重用素材、鎖定排列單改色彩及可調板縫顏色。
- 特殊拼法為解析式初版；Chevron 板長目前表示水平投影長度，實體尺寸與裁角驗收需完善。
- 接縫差異熱圖、16-bit 資料圖、8K 記憶體壓力測試。桌面專案儲存／載入已依使用者要求取消。

本次測試與修改紀錄見 [CHANGELOG.md](CHANGELOG.md)。人工與平台驗收完成前，不能將此初版當作已驗收的正式版本。
