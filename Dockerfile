# Базовый образ с CUDA 12.8.1, cuDNN и Ubuntu 24.04
FROM nvidia/cuda:12.8.1-cudnn-devel-ubuntu24.04

# Установка Python 3.13 из PPA deadsnakes (с повторными попытками)
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    software-properties-common \
    gpg \
    ca-certificates \
    curl \
    && for i in 1 2 3; do \
        add-apt-repository -y ppa:deadsnakes/ppa && break || sleep 5; \
    done \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        python3.13 \
        python3.13-dev \
        python3.13-venv \
    && rm -rf /var/lib/apt/lists/*

# Установка pip для Python 3.13
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.13

# Системные зависимости (включая компиляторы и библиотеки для работы с документами)
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    gcc \
    g++ \
    curl \
    git \
    netcat-openbsd \
    ca-certificates \
    poppler-utils \
    libmagic1 \
    libfreetype6 \
    libjpeg-turbo8 \
    libopenjp2-7 \
    libpng16-16 \
    libtiff6 \
    libxcb1 \
    libxext6 \
    libxrender1 \
    cmake \
    ninja-build \
    patchelf \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PIP_DEFAULT_TIMEOUT=6000 \
    PIP_RETRIES=10

# Виртуальное окружение
RUN python3.13 -m venv /opt/venv
ENV VIRTUAL_ENV="/opt/venv"
ENV PATH="/opt/venv/bin:$PATH"

# Установка uv (быстрый пакетный менеджер)
RUN pip install uv

ENV UV_HTTP_TIMEOUT=6000

# Копируем файл с зависимостями (создадим позже)
COPY requirements.in .

# Компиляция и установка основных зависимостей (без PyTorch, которые установим отдельно)
RUN uv pip compile requirements.in --output-file requirements.txt && \
    uv pip install -r requirements.txt

# Установка PyTorch с CUDA 12.8 из зеркала Alibaba
RUN uv pip install \
    --find-links https://mirrors.aliyun.com/pytorch-wheels/cu128/ \
    torch==2.10.0+cu128 \
    torchvision==0.25.0+cu128 \
    torchaudio==2.10.0+cu128

# bitsandbytes (для квантизации)
RUN uv pip install bitsandbytes==0.49.2

# Копируем код приложения (пока пусто, но для сборки)
COPY . .

# Точка входа
RUN echo '#!/bin/bash\nset -e\necho "=== Starting GPU service ==="\nexec "$@"\n' > /entrypoint.sh && chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]