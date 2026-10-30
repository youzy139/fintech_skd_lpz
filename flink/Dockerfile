FROM maven:3.9.9-eclipse-temurin-17 AS build
WORKDIR /src
COPY flink/pom.xml ./
RUN mvn -B -ntp dependency:go-offline
COPY flink/src ./src
RUN mvn -B -ntp -DskipTests package

FROM apache/flink:2.2.1-scala_2.12-java17
USER root
RUN mkdir -p /opt/flink/checkpoints && chown -R flink:flink /opt/flink/checkpoints
COPY --from=build --chown=flink:flink /src/target/marketlens-flink.jar /opt/marketlens/marketlens-flink.jar
USER flink
