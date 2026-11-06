# TaskHub

FastAPI skeleton theo **Layered Architecture** (AI-friendly): API → Service → Repository → Model.
Không cần activate virtualenv — mọi thứ chạy qua `uv`.

## Yêu cầu

- Python 3.12 (đã pin trong `.python-version`)
- [uv](https://docs.astral.sh/uv/)

## Cài đặt

```powershell
uv python install 3.12
uv sync
```

## Chạy server

```powershell
uv run uvicorn app.main:app --reload --port 8000
```

- Health: http://127.0.0.1:8000/health
- Swagger UI: http://127.0.0.1:8000/docs
- OpenAPI: http://127.0.0.1:8000/openapi.json

## API

Canonical: `/api/v1/tasks`. Alias ngắn `/tasks` cũng hoạt động (ẩn khỏi OpenAPI).

| Method | Path                  | Status | Mô tả                         |
| ------ | --------------------- | ------ | ----------------------------- |
| POST   | `/api/v1/tasks`       | 201    | Tạo task                      |
| GET    | `/api/v1/tasks`       | 200    | Danh sách (`status`, `offset`, `limit`) |
| GET    | `/api/v1/tasks/{id}`  | 200/404| Chi tiết                      |
| PATCH  | `/api/v1/tasks/{id}`  | 200/404| Cập nhật một phần             |
| DELETE | `/api/v1/tasks/{id}`  | 204/404| Xoá                           |

Ví dụ:

```powershell
$body = @{ title = "Viết README"; description = "Mô tả dự án" } | ConvertTo-Json
$task = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/tasks `
  -ContentType "application/json" -Body $body

Invoke-RestMethod -Method Patch -Uri "http://127.0.0.1:8000/api/v1/tasks/$($task.id)" `
  -ContentType "application/json" -Body (@{ status = "done" } | ConvertTo-Json)

Invoke-RestMethod -Method Delete -Uri "http://127.0.0.1:8000/api/v1/tasks/$($task.id)"
```

## Cấu hình

Mọi biến môi trường dùng tiền tố `TASKHUB_`:

| Biến                   | Mặc định    |
| ---------------------- | ----------- |
| `TASKHUB_APP_NAME`     | `TaskHub`   |
| `TASKHUB_VERSION`      | `0.1.0`     |
| `TASKHUB_ENVIRONMENT`  | `local`     |
| `TASKHUB_DEBUG`        | `false`     |
| `TASKHUB_API_V1_PREFIX`| `/api/v1`   |
| `TASKHUB_HOST`         | `127.0.0.1` |
| `TASKHUB_PORT`         | `8000`      |

## Cấu trúc

```
taskhub/
├── app/
│   ├── main.py                  # create_app factory, lifespan, exception handlers
│   ├── api/v1/
│   │   ├── router.py            # gom router v1
│   │   └── tasks.py             # HTTP adapter cho /tasks
│   ├── core/
│   │   ├── config.py            # Settings (env TASKHUB_*)
│   │   ├── deps.py              # DI: repository → service
│   │   └── exceptions.py        # TaskNotFoundError
│   ├── models/task.py           # dataclass slots, UUID, UTC
│   ├── schemas/task.py          # Pydantic v2 Create/Update/Read
│   ├── services/task_service.py # business rules
│   └── repositories/task_repo.py# Protocol + in-memory impl
├── pyproject.toml
├── .python-version
└── README.md
```

## Ghi chú thiết kế

- Repository là in-memory, thread-safe (RLock); thay bằng DB chỉ cần implement lại `TaskRepository`.
- Service không import FastAPI → dễ unit test, dễ tái sử dụng.
- `TaskNotFoundError` được dịch thành HTTP 404 tại composition root (`app/main.py`).
- Timestamp luôn timezone-aware UTC.
