# Airflow image for the wildfire pipeline.
# Base: official Apache Airflow 2.10.5 on Python 3.11. The project dependencies are
# installed against the official constraints file so they never break Airflow's own.
FROM apache/airflow:2.10.5-python3.11

ARG AIRFLOW_VERSION=2.10.5
ARG PYTHON_VERSION=3.11

USER root
RUN apt-get update && \
    apt-get install -y --no-install-recommends openjdk-17-jre-headless procps && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/default-java
RUN ln -sfn /usr/lib/jvm/java-17-openjdk-$(dpkg --print-architecture) /usr/lib/jvm/default-java

USER airflow

COPY docker/airflow/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt"