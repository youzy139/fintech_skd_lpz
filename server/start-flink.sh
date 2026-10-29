#!/usr/bin/env bash
set -euo pipefail

ROOT_WIN=$(pwd -W)
FLINK_HOME_WIN="$ROOT_WIN/server/data/flink/flink-2.2.1"
RUNTIME_WIN="$ROOT_WIN/server/data/flink"
mkdir -p server/data/flink/tmp

if curl --silent --max-time 2 http://127.0.0.1:8081/overview >/dev/null 2>&1; then
  echo "Flink is already running at http://127.0.0.1:8081"
  exit 0
fi

export JAVA_TOOL_OPTIONS="--add-exports=java.rmi/sun.rmi.registry=ALL-UNNAMED --add-exports=jdk.compiler/com.sun.tools.javac.api=ALL-UNNAMED --add-exports=jdk.compiler/com.sun.tools.javac.file=ALL-UNNAMED --add-exports=jdk.compiler/com.sun.tools.javac.parser=ALL-UNNAMED --add-exports=jdk.compiler/com.sun.tools.javac.tree=ALL-UNNAMED --add-exports=jdk.compiler/com.sun.tools.javac.util=ALL-UNNAMED --add-exports=java.security.jgss/sun.security.krb5=ALL-UNNAMED --add-opens=java.base/java.lang=ALL-UNNAMED --add-opens=java.base/java.net=ALL-UNNAMED --add-opens=java.base/java.io=ALL-UNNAMED --add-opens=java.base/java.nio=ALL-UNNAMED --add-opens=java.base/sun.nio.ch=ALL-UNNAMED --add-opens=java.base/java.lang.reflect=ALL-UNNAMED --add-opens=java.base/java.text=ALL-UNNAMED --add-opens=java.base/java.time=ALL-UNNAMED --add-opens=java.base/java.util=ALL-UNNAMED --add-opens=java.base/java.util.concurrent=ALL-UNNAMED --add-opens=java.base/java.util.concurrent.atomic=ALL-UNNAMED --add-opens=java.base/java.util.concurrent.locks=ALL-UNNAMED -Djava.security.manager=allow"

nohup java -cp "$FLINK_HOME_WIN/lib/*" org.apache.flink.runtime.entrypoint.StandaloneSessionClusterEntrypoint \
  --configDir "$FLINK_HOME_WIN/conf" --executionMode cluster > server/data/flink/jobmanager.log 2>&1 &
echo $! > server/data/flink/jobmanager.pid

nohup java -cp "$FLINK_HOME_WIN/lib/*" org.apache.flink.runtime.taskexecutor.TaskManagerRunner \
  --configDir "$FLINK_HOME_WIN/conf" \
  -D taskmanager.resource-id=local-tm-1 \
  -D taskmanager.cpu.cores=1 \
  -D taskmanager.memory.process.size=2304m \
  -D taskmanager.memory.task.heap.size=1024m \
  -D taskmanager.memory.task.off-heap.size=256m \
  -D taskmanager.memory.framework.heap.size=128m \
  -D taskmanager.memory.framework.off-heap.size=128m \
  -D taskmanager.memory.managed.size=256m \
  -D taskmanager.memory.network.min=64m \
  -D taskmanager.memory.network.max=64m \
  -D taskmanager.memory.jvm-metaspace.size=256m \
  -D taskmanager.memory.jvm-overhead.min=256m \
  -D taskmanager.memory.jvm-overhead.max=256m \
  -D process.taskmanager.working-dir="$RUNTIME_WIN/tm-work" \
  -D io.tmp.dirs="$RUNTIME_WIN/tmp" > server/data/flink/taskmanager.log 2>&1 &
echo $! > server/data/flink/taskmanager.pid

echo "Flink JobManager and TaskManager started"
