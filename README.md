# Personal Home Automation Project

This repository contains configs for my home services. It is based on a Raspberry Pi that runs several services in Docker containers to control and manage various aspects of my home environment. Each service is configured through Docker Compose for easy deployment and management.

## Services

The following services are included in this project:

### 1. Homepage

The homepage service is a custom dashboard that provides a unified interface to various home automation services. It uses the image `ghcr.io/benphelps/homepage:main`.

#### Environment Variables
The service requires several environment variables for configuration. These variables should be replaced with your actual data.

- `HOMEPAGE_VAR_DISKSTATION_URL`: The URL of your DiskStation.
- `HOMEPAGE_VAR_DISKSTATION_USER`: Your DiskStation username.
- `HOMEPAGE_VAR_DISKSTATION_PASSWORD`: Your DiskStation password.
- `HOMEPAGE_VAR_HOMEBRIDGE_URL`: The URL of your Homebridge.
- `HOMEPAGE_VAR_HOMEBRIDGE_USER`: Your Homebridge username.
- `HOMEPAGE_VAR_HOMEBRIDGE_PASSWORD`: Your Homebridge password.
- `HOMEPAGE_VAR_ZIMA_GRAFANA_URL`: The URL of your Grafana instance.
- `HOMEPAGE_VAR_ZIMA_GRAFANA_USER`: Your Grafana username.
- `HOMEPAGE_VAR_ZIMA_GRAFANA_PASSWORD`: Your Grafana password.

#### Volumes
Two volumes are mounted for the homepage service:
- `/var/run/docker.sock` is shared with the host to enable container management from within the service.
- `./homepage/config` is mounted to `/app/config` in the container for configuration data.

### 2. Homebridge

Homebridge is a lightweight Node.js server that emulates the iOS HomeKit API. It allows you to integrate with smart home devices that do not natively support HomeKit. This service uses the image `oznu/homebridge:latest`.

#### Volumes
A single volume, `./volumes/homebridge`, is mounted to `/homebridge` in the container for persistent data.

#### Logging
The logging driver used is `json-file` with a maximum file size of 10MB and a maximum of 1 file.

### 3. iSponsorBlockTV

iSponsorBlockTV is a service that automatically skips sponsored messages and other specified segments in YouTube videos on your TV. It uses the image `ghcr.io/dmunozv04/isponsorblocktv:latest`.

#### Volumes
A single volume, `./iSponsorBlockTV/config.json`, is mounted to `/app/config.json` in the container for configuration data.

## Setup

To deploy these services, follow these steps:

1. Clone this repository to your Raspberry Pi.
2. Update the environment variables in the Docker Compose file with your own settings.
3. Run the Docker Compose file with `docker-compose up -d`.

## Contributing

If you have suggestions for how this project could be improved, feel free to open an issue or a pull request.

## License

This project is open source, under the terms of the [MIT license](/LICENSE).
