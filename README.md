# Texture Studio

繁體中文、本機運算的無縫貼圖與板材生成器。Python 3.11+、PySide6、OpenCV、NumPy、Pillow；無須外部 API、帳號或 API Key。

目前為可執行初版，不代表規格書 v1.0 全部完成驗收。核心演算法獨立於 UI，計算與圖片讀寫使用背景工作執行緒。取消在演算法步驟與板片之間生效，單次 FFT／解碼不能立即中斷。

## Windows 10／11

安裝 64-bit Python 3.11（包含 Python Launcher），執行：

```bat
setup_windows.bat
start_windows.bat
build_windows.bat
```

打包結果為 `dist\TextureStudio\TextureStudio.exe`，需分發**整個 TextureStudio 資料夾**。目標電腦不需 Python。打包必須在 Windows 執行；Linux 無法藉此產生 Windows EXE。本次沒有產生或驗證 Windows EXE。

Python 3.12 或更新版本可手動建立環境：

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m texture_studio
```

Linux 伺服器測試設定 `QT_QPA_PLATFORM=offscreen`。離屏模式不提供可互動桌面，實際操作需有圖形顯示環境。

## 使用方式

1. 拖入或匯入 JPG、PNG、TIFF、BMP。支援中文路徑、EXIF 方向及 ICC 至 sRGB 轉換。RGB 工作流程不保留透明度或 16-bit 通道。
2. 選擇「無縫貼圖」，調整光照強度、範圍、原始明暗保留與週期性重建強度，按「自動處理」。深色木紋誤被校正時，降低強度或提高明暗保留。
3. 使用 1／2／3／5 重複預覽、原圖比較、接縫輔助線；滾輪縮放、拖曳平移。「回到上次結果」保留一次生成結果復原。
4. 「隨機變體」提供 2–50 張、Seed、方向保護、鏡像、任意角度；亮度／色相／飽和度／對比可獨立設為 0 關閉。變體不是新紋理合成。
5. 「板材生成」輸入板寬、板長、整面尺寸、板縫、倒角與解析度。素材以保留比例的中心裁切符合板片，長軸自動判定，不直接拉伸。
6. 排列：`straight` 直鋪、`half`／`third`／`quarter` 固定錯縫、`random` 隨機錯縫、`variable` 隨機長短板、`custom` 自訂錯縫；另有解析式 `herringbone` 人字拼、`chevron` 魚骨拼、`basketweave` 籃編拼。
7. 板縫寬設為 0 可輸出無板縫版本；Base Color 不加入假倒角光影，以高度參考圖表示倒角。可選擇更多材質參考圖。
8. 選取輸出可獨立預覽與匯出 PNG／JPG／TIFF；批次輸出 PNG 與 JSON。原素材不會被覆寫。JSON 記錄來源、參數、Seed、版本、實際尺寸與 UV 比例，重新開啟後按處理生成。移動素材後需重新匯入。

預設拼板實際尺寸 3600×1800 mm；請在 3ds Max 依 JSON 設定實際 UV 尺寸。週期模式要求整面尺寸符合排列週期，不相容時明確拒絕；請調整尺寸或關閉週期模式。拼板接縫包含真實板縫，不能只靠首末像素差判斷自然程度。

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
- `ui.py`：介面與工作執行緒；`cli.py`：無 GUI 批次處理。

## 色彩與影像處理限制

Base Color 附 sRGB profile；Mask／Height／Roughness／Normal 不附 sRGB profile，在 Corona／3ds Max 中應設定 linear／non-color。Normal 需配合材質的法線方向設定。高度、粗糙度、法線僅為 RGB 推估，不能恢復量測的反射率或幾何。

週期性 Poisson 分解移除造成邊界跳變的平滑分量，不在中央做交叉羽化；但不是高階內容感知合成，也不保證所有天然紋理無可見重複。明暗與材質固有深色無法單從 RGB 完美區分，務必目視檢查。首末像素是相隔一個取樣點的相鄰像素，差值通常不是零。

## 驗證與尚待完成的驗收

執行 `python -m pytest -q`。測試包含合成木紋／石材／布料、細節保留、明暗漸層、中文檔名、Seed、任意旋轉、標準／特殊排列、拒絕不相容週期、法線向量、真實 PNG 匯出、Qt 背景工作與 JSON 記錄。

尚未完成整份規格的產品驗收：

- 真實素材人工品質驗收、Windows 10／11 操作、EXE 啟動及 3ds Max／Corona 實測。
- 素材手動裁切、旋轉校正、排序／完整縮圖管理、局部板片替換與互動自訂排法。
- 嚴格跨列最短錯縫、上下相鄰素材去重、禁止重用素材、鎖定排列單改色彩及可調板縫顏色。
- 特殊拼法為解析式初版；Chevron 板長目前表示水平投影長度，實體尺寸與裁角驗收需完善。
- 接縫差異熱圖、完整專案格式驗證與遷移、16-bit 資料圖、8K 記憶體壓力測試。

本次測試與修改紀錄見 [CHANGELOG.md](CHANGELOG.md)。人工與平台驗收完成前，不能將此初版當作已驗收的正式版本。
