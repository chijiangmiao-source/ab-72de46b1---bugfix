# 光刻版缺陷复核服务 (photomask defect audit)

对 1–50000 个轴对齐矩形污染框计算**并集面积**与**外露周长**（union area /
exposed perimeter）。重叠、相切、完全包围都按并集裁决：相接边不计入周长，
几何重复不增量。

## 算法

纯 Python 大整数实现（`app/geometry.py`），不铺开单位网格、不成对切割矩形、
不依赖任何几何求解库：

1. 两次正交的一维扫描线（x 方向得面积与垂直边界，换轴得水平边界）。
2. 坐标压缩 + 迭代式懒标记线段树维护离散坐标上的覆盖计数与覆盖总长，
   单次事件 O(log n)。
3. 同一扫描坐标的全部事件**整体裁决**，且进入 (+1) 先于离开 (−1)：
   该坐标处覆盖长度的翻转总量等于事件前后覆盖集的对称差测度，因此一个框
   离开、另一个框进入的相接边净变化为 0，不会形成内部周长。
4. 所有坐标与结果均为精确整数；HTTP 响应中结果以**十进制字符串**返回。

5 万随机矩形端到端约 1–2 秒。

## API

`POST /api/audit`

```json
{
  "rectangles": [
    {"id": "a", "x0": 0, "y0": 0, "x1": 3, "y1": 2},
    {"id": "b", "x0": 2, "y0": 0, "x1": 5, "y1": 2}
  ]
}
```

- `id`：字符串或整数，全局唯一；**标识重复一律拒绝**（几何重合允许）。
- 四个坐标均为整数，绝对值 ≤ 10⁹，且严格满足 `x0 < x1`、`y0 < y1`。

成功响应（200）：

```json
{"count": 2, "area": "10", "perimeter": "14"}
```

失败响应（422）不含任何部分结果，错误带输入位置且顺序稳定：

```json
{
  "error": "validation_failed",
  "message": "request validation failed",
  "errors": [
    {"loc": "/rectangles/1/id", "code": "duplicate_id",
     "message": "duplicate rectangle id \"x\"; first seen at index 0"}
  ]
}
```

`GET /health` 仅在请求校验器与扫描引擎**均就绪**时返回 200，否则 503；
响应体逐项给出两个组件的状态。

## 运行

```bash
# 默认宿主机端口 8080，可用 AUDIT_HOST_PORT 覆盖
AUDIT_HOST_PORT=9000 docker compose up -d --build audit
curl -s localhost:9000/health
```

## 一次性校验 (verify)

verify 服务在 audit 通过健康检查后运行一次：pytest 代码测试、构建检查
（字节码编译 + ASGI 应用/校验器/引擎导入）、API/HTTP 冒烟（覆盖重叠框
面积 10 周长 14、相邻方框不计公共边、重复框不增量、64 个同起点高密度框
（32+32，纵向重叠/包含）面积 25 周长 34 且 count=64、重复 id 被拒），随后
退出并以退出码报告结果：

```bash
docker compose up --build --abort-on-container-exit --exit-code-from verify verify
# 或
docker compose run --build verify; echo "exit=$?"
```

退出码 0 表示全部通过，非 0 表示存在失败项。

## 本地开发

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-verify.txt
.venv/bin/python -m pytest -q
```
