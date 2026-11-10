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
Copy-Item .env.example .env
docker run -d --name taskhub-db -e POSTGRES_PASSWORD=taskhub -e POSTGRES_DB=taskhub -p 5432:5432 postgres:16
uv run alembic upgrade head
```

Before starting the app, set a private signing key of at least 32 bytes and apply database migrations with `uv run alembic upgrade head`:

```powershell
$env:TASKHUB_JWT_SECRET_KEY = (python -c "import secrets; print(secrets.token_urlsafe(48))")
```

`uv run alembic downgrade base` removes all tables; use it only for a disposable DB.

### Chuyển database Day 2 cũ

Migration đầu tạo schema theo `day2-brief.md`; revision tiếp theo thêm bảng phiên refresh.
Hai revision cũ
`552a3882346e` và `9e5ac2ec2ba3` không nằm trong migration graph mới. Để chuyển
database có dữ liệu, dừng ứng dụng và tạo backup đã kiểm tra trước. Chạy preflight
(không ghi dữ liệu), sau đó mới chạy lệnh `--apply` rõ ràng:

```powershell
$url = "postgresql+asyncpg://postgres:taskhub@localhost:5432/taskhub_test"
uv run python -m scripts.upgrade_day2_legacy --database-url $url
uv run python -m scripts.upgrade_day2_legacy --database-url $url --apply
uv run alembic current
```

Lệnh mặc định chỉ đọc; tool yêu cầu URL tường minh và từ chối database không có
hậu tố `_test` nếu thiếu `--allow-non-test-database`. Chỉ dùng cờ đó sau khi đã
backup và xác nhận URL đích. Chuyển đổi nằm trong một transaction và giữ dữ liệu:
đổi tên `name`, `created_by_id`, `body`; thêm description, password hash vô hiệu,
màu mặc định và timestamps; label được gắn với project duy nhất trong workspace.
Nếu workspace của label có 0 hoặc nhiều hơn 1 project, preflight dừng trước khi
ghi. Các enum cũ được giữ nguyên; không tự drop type vì chúng có thể còn được
dùng. Lệnh không chạy tự động khi khởi động ứng dụng.

Nếu không thể dùng utility, cách duy nhất được hỗ trợ là backup dữ liệu, xác nhận
đích rõ ràng, tạo database rỗng mới và chạy revision ban đầu; không chạy
`alembic downgrade base` trên database có dữ liệu vì thao tác đó xóa bảng.

## Chạy server

```powershell
uv run uvicorn app.main:app --reload --port 8000
```

- Health: http://127.0.0.1:8000/health
- Swagger UI: http://127.0.0.1:8000/docs
- OpenAPI: http://127.0.0.1:8000/openapi.json

## API

Canonical: `/api/v1/tasks`. Alias ngắn `/tasks` cũng hoạt động (ẩn khỏi OpenAPI).

Auth: `POST /api/v1/auth/register`, `/login`, `/refresh`, `/logout`;
`GET/PATCH /api/v1/users/me`; `POST /api/v1/users/me/change-password`.
Access tokens dùng Bearer auth; refresh token chỉ nằm trong cookie HttpOnly,
host-only, `Secure`, `SameSite=Lax` mặc định và giới hạn ở `/api/v1/auth`.
Login chấp nhận client không gửi `Origin` như curl, Postman hoặc mobile; nếu header
được gửi, API kiểm tra origin phải trùng origin API hoặc một origin trong
`TASKHUB_FRONTEND_ORIGINS`. Refresh/logout luôn yêu cầu `Origin` hợp lệ vì dùng
refresh cookie. CORS credentials chỉ bật cho danh sách origin tường minh này.
Refresh tokens được xoay vòng và lưu trạng thái thu hồi trong PostgreSQL. Nếu một
refresh token còn hạn đã bị thu hồi được dùng lại, API thu hồi toàn bộ refresh
session của tài khoản. Vì vậy refresh đồng thời ở nhiều tab có thể khiến một
tab dùng lại token cũ và đăng xuất các tab/thiết bị còn lại; ứng dụng browser nên
single-flight refresh và tuần tự hóa các thao tác auth giữa các tab.
Đăng ký luôn cấp role `member`; profile không cho sửa
role, trạng thái hoạt động hoặc mật khẩu. Logout và đổi mật khẩu thu hồi refresh
tokens; access token đã phát hành còn hiệu lực tới khi hết hạn. Task endpoints hiện
vẫn public; dự kiến Day 4 sẽ yêu cầu Bearer token và kiểm tra quyền theo
workspace/project khi phần authorization đó được triển khai.

Browser integration được hoãn tới Day 4. Với frontend khác origin, cấu hình
origin chính xác, ví dụ `TASKHUB_FRONTEND_ORIGINS='["https://app.example.com"]'`.
Cookie cross-origin cần cùng site (cùng eTLD+1); `SameSite=None` chỉ dùng cùng
với Secure và HTTPS.

Trong PowerShell local HTTP, có thể opt out Secure rõ ràng:

```powershell
$env:TASKHUB_REFRESH_COOKIE_SECURE = "false"
```

SDK/curl có thể bỏ `Origin` khi login; refresh/logout cần gửi `Origin` hợp lệ, ví dụ
`Origin: http://127.0.0.1:8000`. Cookie refresh được browser gửi tự động; API
không nhận refresh token trong JSON hoặc Authorization header.

| Method | Path                  | Status | Mô tả                         |
| ------ | --------------------- | ------ | ----------------------------- |
| POST   | `/api/v1/tasks`       | 201    | Tạo task                      |
| GET    | `/api/v1/tasks`       | 200    | Danh sách và `total` (`status`, `offset`, `limit`) |
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
| `TASKHUB_DATABASE_URL` | `postgresql+asyncpg://postgres:taskhub@localhost:5432/taskhub` |
| `TASKHUB_DATABASE_ECHO` | `false` |
| `TASKHUB_JWT_SECRET_KEY` | bắt buộc, tối thiểu 32 bytes |
| `TASKHUB_ACCESS_TOKEN_MINUTES` | `15` |
| `TASKHUB_REFRESH_TOKEN_DAYS` | `30` |
| `TASKHUB_REFRESH_COOKIE_SECURE` | `true` (production bắt buộc) |
| `TASKHUB_REFRESH_COOKIE_SAMESITE` | `lax` |
| `TASKHUB_FRONTEND_ORIGINS` | `[]` (JSON list origin chính xác) |

## Kiểm thử database

Integration tests chỉ chạy trên PostgreSQL database riêng tên `taskhub_test`.
Tạo database test rồi chạy:

```powershell
docker exec taskhub-db createdb -U postgres taskhub_test
$env:TASKHUB_TEST_DATABASE_URL = "postgresql+asyncpg://postgres:taskhub@localhost:5432/taskhub_test"
uv run python -m unittest discover -s tests -v
```

Test migration chạy `downgrade base` rồi `upgrade head`; sau test sẽ downgrade về `base`.
Không đặt `TASKHUB_TEST_DATABASE_URL` trỏ vào database ứng dụng.

## Cấu trúc

```
taskhub/
├── app/
│   ├── api/v1/
│   │   ├── router.py            # API v1 aggregation
│   │   ├── auth.py              # register/login/refresh/logout HTTP adapter
│   │   ├── users.py             # current-user HTTP adapter
│   │   └── tasks.py             # task HTTP adapter
│   ├── core/
│   │   ├── config.py            # Settings (env TASKHUB_*)
│   │   ├── deps.py              # request-scoped dependency wiring
│   │   ├── constants.py         # shared validation and error constants
│   │   ├── exceptions.py        # application/domain exceptions
│   │   └── security.py          # password hashing and JWT validation
│   ├── db/                      # engine, metadata, seed, legacy utility
│   ├── models/                  # entities, enums, and task domain model
│   ├── repositories/            # PostgreSQL task and user persistence
│   ├── schemas/                 # Pydantic request, response, and shared types
│   ├── services/                # task and auth business rules
│   └── main.py                  # app factory, middleware, exception handlers
├── alembic/versions/            # schema migrations
├── tests/                       # unit and PostgreSQL integration tests
├── pyproject.toml
├── .python-version
└── README.md
```

## Ghi chú thiết kế

- Repository SQLAlchemy async persist vào PostgreSQL; `InMemoryTaskRepository` vẫn có thể dùng trong unit test.
- Service không import FastAPI → dễ unit test, dễ tái sử dụng.
- `TaskNotFoundError` được dịch thành HTTP 404 tại composition root (`app/main.py`).
- Timestamp luôn timezone-aware UTC.
