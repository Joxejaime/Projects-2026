APP_VERSION ?= dev
IMAGE ?= release-tracker:$(APP_VERSION)

.PHONY: lint test docker-lint build run verify

lint:
	cd app && ruff check .

test:
	cd app && python3 -m unittest discover -s tests -v

docker-lint:
	hadolint Dockerfile

build:
	docker build --build-arg APP_VERSION=$(APP_VERSION) -t $(IMAGE) .

run: build
	docker run --rm -p 8080:8080 --read-only --cap-drop ALL --security-opt no-new-privileges $(IMAGE)

verify: lint test docker-lint
