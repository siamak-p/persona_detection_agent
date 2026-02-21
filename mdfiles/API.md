# JoowMe Agent — API Reference

> **Base URL:** `http://localhost:8000`
> **Framework:** FastAPI 1.0.0 (title: *PetaProcTwin API*)

---

## Table of Contents

- [Health Check](#health-check)
- [Chat](#chat)
- [Creator](#creator)
- [Passive Observation](#passive-observation)
- [Relationship Feedback](#relationship-feedback)
- [Future Planning Requests](#future-planning-requests)
- [Financial Threads](#financial-threads)
- [Voice Files](#voice-files)
- [WebSocket Notifications](#websocket-notifications)
- [Admin — Scheduler](#admin--scheduler)
- [Observability](#observability)

---

## Health Check

### `GET /health`

Returns service health status and available endpoints.

**Response:**

```json
{
  "status": "healthy",
  "message": "PetaProcTwin API is running",
  "observability": {
    "phoenix_ui": "http://localhost:6006",
    "grafana": "http://localhost:3001",
    "prometheus": "http://localhost:9091"
  },
  "endpoints": ["POST /api/v1/chat", "..."]
}
```

---

## Chat

### `POST /api/v1/chat`

Send a message from a user to an AI Twin and receive the twin's response.

**Headers:**

| Header             | Type   | Required | Description                      |
|--------------------|--------|----------|----------------------------------|
| `X-Correlation-Id` | string | No       | Correlation ID for request tracing |

**Request Body (`ChatRequest`):**

| Field            | Type   | Required | Default  | Description                                     |
|------------------|--------|----------|----------|-------------------------------------------------|
| `user_id`        | string | ✅       |          | Sending user identifier                          |
| `to_user_id`     | string | ✅       |          | Recipient (twin owner) user identifier           |
| `language`       | string | No       | `"fa"`   | Response language (ISO 639-1)                    |
| `message`        | string | No       | `""`     | Text message content (empty if voice)            |
| `message_id`     | string | No       | `null`   | Client-side message identifier                   |
| `conversation_id`| string | ✅       |          | Conversation identifier                          |
| `timestamp`      | string | ✅       |          | ISO 8601 timestamp                               |
| `voice_data`     | string | No       | `null`   | Base64-encoded audio data                        |
| `input_type`     | string | No       | `"text"` | `"text"` or `"voice"`                            |
| `voice_format`   | string | No       | `"webm"` | Audio format (`webm`, `opus`, `mp3`, `wav`)      |

**Response (`ChatResponse`):**

| Field              | Type   | Description                         |
|--------------------|--------|-------------------------------------|
| `user_id`          | string | Recipient user identifier           |
| `agent_message`    | string | Agent-generated text response       |
| `agent_message_id` | string | Agent-generated message identifier  |
| `conversation_id`  | string | Conversation identifier             |
| `agent_timestamp`  | string | Agent-generated ISO timestamp       |
| `correlation_id`   | string | Correlation tracking ID             |
| `agent_voice_url`  | string | URL to TTS audio file (if voice)    |
| `output_type`      | string | `"text"` or `"voice"`               |

---

## Creator

### `POST /api/v1/creator`

Send a message from the owner (creator) to their own twin for learning / conversation.

**Headers:**

| Header             | Type   | Required | Description            |
|--------------------|--------|----------|------------------------|
| `X-Correlation-Id` | string | No       | Correlation tracking ID |

**Request Body (`CreatorRequest`):**

| Field          | Type   | Required | Default  | Description                         |
|----------------|--------|----------|----------|-------------------------------------|
| `user_id`      | string | ✅       |          | Creator user identifier             |
| `language`     | string | No       | `"fa"`   | Response language (ISO 639-1)       |
| `message`      | string | No       | `""`     | Text message (empty if voice)       |
| `message_id`   | string | No       | `null`   | Client message identifier           |
| `timestamp`    | string | ✅       |          | ISO 8601 timestamp                  |
| `voice_data`   | string | No       | `null`   | Base64-encoded audio data           |
| `input_type`   | string | No       | `"text"` | `"text"` or `"voice"`               |
| `voice_format` | string | No       | `"webm"` | Audio format                        |

**Response (`CreatorResponse`):**

| Field              | Type   | Description                         |
|--------------------|--------|-------------------------------------|
| `user_id`          | string | Original user identifier            |
| `agent_message`    | string | Agent-generated response            |
| `agent_message_id` | string | Agent-generated message identifier  |
| `agent_timestamp`  | string | Agent-generated timestamp           |
| `correlation_id`   | string | Correlation tracking ID             |
| `agent_voice_url`  | string | URL to voice response file (if any) |
| `output_type`      | string | `"text"` or `"voice"`               |

---

## Passive Observation

### `POST /api/v1/passive`

Record passive observation messages (messages the twin observes but doesn't respond to directly).

**Headers:**

| Header             | Type   | Required | Description            |
|--------------------|--------|----------|------------------------|
| `X-Correlation-Id` | string | No       | Correlation tracking ID |

**Request Body:** `List[PassiveRecordItem]`

Each item:

| Field            | Type   | Required | Default  | Description                         |
|------------------|--------|----------|----------|-------------------------------------|
| `user_id`        | string | ✅       |          | User identifier                     |
| `to_user_id`     | string | ✅       |          | Counterpart user identifier         |
| `language`       | string | No       | `"fa"`   | Language (ISO 639-1)                |
| `conversation_id`| string | ✅       |          | Conversation identifier             |
| `message`        | string | No       | `""`     | Message content (empty if voice)    |
| `message_id`     | string | ✅       |          | Message identifier                  |
| `timestamp`      | string | ✅       |          | ISO 8601 timestamp                  |
| `voice_data`     | string | No       | `null`   | Base64-encoded audio (optional)     |
| `input_type`     | string | No       | `"text"` | `"text"` or `"voice"`               |
| `voice_format`   | string | No       | `"webm"` | Audio format                        |

**Response (`PassiveRecordResponse`):**

| Field            | Type    | Description                      |
|------------------|---------|----------------------------------|
| `received`       | boolean | Indicates successful ingestion   |
| `agent_timestamp` | string | Agent timestamp                 |
| `correlation_id` | string  | Correlation tracking ID          |

### `GET /api/v1/passive/last-msgId`

Get the last synced passive message ID.

**Response (`PassiveLastMessageIdResponse`):**

| Field      | Type   | Description                          |
|------------|--------|--------------------------------------|
| `lastMsgId`| string | Last synced message identifier       |

---

## Relationship Feedback

### `GET /api/v1/feedback/questions/{user_id}`

Get all pending relationship questions and future requests for a user.

**Response (`QuestionsListResponse`):**

| Field             | Type    | Description                                      |
|-------------------|---------|--------------------------------------------------|
| `questions`       | array   | List of `QuestionResponse` objects                |
| `future_requests` | array   | List of `FutureRequestResponse` objects           |
| `has_unread`      | boolean | Whether there are unread questions/requests       |
| `total_count`     | integer | Total number of questions and requests            |

### `GET /api/v1/feedback/has-unread/{user_id}`

Check if a user has unread questions, future requests, or financial threads.

**Response (`HasUnreadResponse`):**

| Field        | Type    | Description                      |
|--------------|---------|----------------------------------|
| `has_unread` | boolean | Has unread items                 |
| `count`      | integer | Total unread count               |

### `GET /api/v1/feedback/limit-status/{user_id}`

Get the question rate-limiting status for a user.

**Response (`QuestionLimitStatusResponse`):**

| Field                        | Type    | Description                              |
|------------------------------|---------|------------------------------------------|
| `questions_asked_in_window`  | integer | Questions asked in current window        |
| `questions_remaining`        | integer | Questions remaining in current window    |
| `max_questions_per_window`   | integer | Maximum questions per window             |
| `window_hours`               | integer | Window duration in hours                 |
| `window_description`         | string  | Human-readable Farsi description         |

### `POST /api/v1/feedback/answer`

Submit a relationship answer.

**Request Body (`SubmitAnswerRequest`):**

| Field                | Type   | Required | Description                                                 |
|----------------------|--------|----------|-------------------------------------------------------------|
| `question_id`        | int    | ✅       | Question identifier                                         |
| `relationship_class` | string | ✅       | `spouse`, `family`, `boss`, `subordinate`, `colleague`, `friend`, `stranger` |
| `answer_text`        | string | No       | Optional explanation                                        |

**Response:** `{ "success": true, "message": "..." }`

### `POST /api/v1/feedback/skip`

Skip a relationship question.

**Request Body:** `{ "question_id": <int> }`

**Response:** `{ "success": true, "message": "..." }`

### `GET /api/v1/feedback/relationship-classes`

Get the list of valid relationship classes with descriptions and emojis.

**Response:**

```json
{
  "classes": [
    { "id": "spouse", "name": "همسر", "emoji": "💑", "description": "..." },
    { "id": "family", "name": "خانواده", "emoji": "👨‍👩‍👧‍👦", "description": "..." },
    ...
  ]
}
```

---

## Future Planning Requests

### `GET /api/v1/feedback/future-requests/{user_id}`

Get pending future-planning requests for a creator (twin owner).

**Response (`FutureRequestsListResponse`):**

| Field        | Type    | Description                     |
|--------------|---------|---------------------------------|
| `requests`   | array   | List of `FutureRequestResponse` |
| `total_count`| integer | Total number of requests        |

### `POST /api/v1/feedback/future-requests/respond`

Submit a creator's response to a future-planning request.

**Request Body (`SubmitFutureResponseRequest`):**

| Field           | Type   | Required | Description                    |
|-----------------|--------|----------|--------------------------------|
| `request_id`    | int    | ✅       | Request identifier             |
| `response_text` | string | ✅       | Creator's response             |

**Response:** `{ "success": true, "message": "..." }`

### `GET /api/v1/feedback/future-requests/count/{user_id}`

Get the count of pending future-planning requests.

**Response:** `{ "count": <int>, "has_pending": <bool> }`

### `GET /api/v1/feedback/my-requests/{sender_id}`

Get future-planning requests sent by a specific user.

**Response:**

```json
{
  "requests": [
    {
      "id": 1,
      "recipient_id": "...",
      "original_message": "...",
      "detected_plan": "...",
      "status": "pending|answered|delivered",
      "creator_response": "..." ,
      "responded_at": "...",
      "created_at": "..."
    }
  ],
  "total_count": 1,
  "pending_count": 0,
  "answered_count": 1
}
```

---

## Financial Threads

### `GET /api/v1/feedback/financial-threads/{user_id}`

Get open financial conversation threads for a creator.

**Response (`FinancialThreadsListResponse`):**

| Field                        | Type    | Description                          |
|------------------------------|---------|--------------------------------------|
| `threads`                    | array   | List of `FinancialThreadResponse`    |
| `total_count`                | integer | Total open threads                   |
| `waiting_for_response_count` | integer | Threads waiting for creator response |

Each thread includes:

| Field                     | Type   | Description                            |
|---------------------------|--------|----------------------------------------|
| `id`                      | int    | Thread identifier                      |
| `sender_id`               | string | Sender user identifier                 |
| `sender_name`             | string | Sender name (if known)                 |
| `relationship_type`       | string | Relationship class (if known)          |
| `topic_summary`           | string | Summary of the financial topic         |
| `last_sender_message`     | string | Last message from sender               |
| `last_creator_response`   | string | Last response from creator             |
| `recent_messages`         | array  | Recent thread messages                 |
| `status`                  | string | Thread status                          |
| `waiting_for`             | string | Who is currently expected to respond   |
| `created_at`              | string | Thread creation time                   |
| `last_activity_at`        | string | Last activity timestamp                |

### `POST /api/v1/feedback/financial-threads/respond`

Submit a creator's response to a financial thread.

**Request Body (`SubmitFinancialResponseRequest`):**

| Field           | Type   | Required | Description                    |
|-----------------|--------|----------|--------------------------------|
| `thread_id`     | int    | ✅       | Thread identifier              |
| `response_text` | string | ✅       | Creator's response text        |

**Response:** `{ "success": true, "message": "..." }`

### `DELETE /api/v1/feedback/financial-threads/{thread_id}`

Close a financial thread.

**Response:** `{ "success": true, "message": "..." }`

---

## Voice Files

### `GET /voices/{conversation_id}/{filename}`

Serve a stored voice file for a given conversation.

**Path Parameters:**

| Parameter         | Type   | Description             |
|-------------------|--------|-------------------------|
| `conversation_id` | string | Conversation identifier |
| `filename`        | string | Voice file name         |

**Response:** Audio file (`audio/mpeg`)

**Error Codes:**
- `404` — Voice file not found
- `403` — Path traversal attempt blocked

---

## WebSocket Notifications

### `WS /api/v1/ws/{user_id}`

Real-time WebSocket connection for push notifications.

**Connection:** `ws://localhost:8000/api/v1/ws/{user_id}`

**Notification types sent by the server:**

| Type                      | Description                                               |
|---------------------------|-----------------------------------------------------------|
| `future_response`         | Creator responded to a future-planning request            |
| `future_request`          | New future-planning request detected for the creator      |
| `financial_topic`         | New financial topic detected for the creator              |
| `financial_message`       | New message added to a financial thread                   |
| `financial_response`      | Creator responded to a financial thread                   |
| `ping`                    | Server heartbeat (every 30 seconds)                       |

### `GET /api/v1/ws/status`

Get WebSocket connection status.

**Response:**

```json
{
  "connected_users": 2,
  "users": ["user_id_1", "user_id_2"]
}
```

---

## Admin — Scheduler

> **Prefix:** `/api/v1/admin/scheduler`

### `POST /run/tone`

Manually trigger the tone detection scheduler.

### `POST /run/tone-retry`

Manually trigger the tone retry worker.

### `GET /stats/tone-retry`

Get tone retry queue statistics.

### `POST /run/feedback`

Manually trigger the feedback (relationship question generation) scheduler.

### `POST /run/chat-summary`

Manually trigger summarization for a specific conversation.

**Request Body (`ChatSummaryRequest`):**

| Field            | Type   | Required | Description                    |
|------------------|--------|----------|--------------------------------|
| `user_id`        | string | ✅       | Primary user identifier        |
| `to_user_id`     | string | ✅       | Other user identifier          |
| `conversation_id`| string | ✅       | Conversation identifier        |

### `POST /run/retry`

Manually trigger the summary retry worker.

### `GET /stats/summary-retry`

Get summary retry queue statistics.

### `GET /status`

Get full scheduler status (intervals, active flags, retry queue stats).

### `POST /run/passive-summarization`

Manually trigger passive summarization scheduler.

### `POST /run/passive-summarization-retry`

Manually trigger passive summarization retry worker.

### `GET /stats/passive-summarization`

Get passive summarization retry stats.

### `POST /retry-failed/passive-summarization/{failed_id}`

Retry a specific failed passive summarization.

### `GET /failed/passive-summarization`

List failed passive summarizations (paginated with `limit` and `offset` query params).

---

## Observability

### `GET /metrics`

Prometheus metrics endpoint (scraped by Prometheus at configured interval).

**Available metric categories:**
- HTTP request counts, latency, and status codes
- LLM token usage (prompt, completion, total)
- Chat, creator, and passive endpoint performance
- Scheduler run counts and durations
- SQLite database metrics (file size, table sizes, memory entries)
