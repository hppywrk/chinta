from ubuntu:noble

# Set environment variables to avoid interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Configuration files
COPY ./rootfs /

RUN apt-get update

# Install tool chain
RUN apt-get install -y build-essential



RUN systemctl enable chinta.service
