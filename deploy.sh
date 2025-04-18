eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_rsa_zy

git stash
sleep 1

git pull origin master
sleep 3

PORT=6010

PID=$(lsof -i :$PORT -sTCP:LISTEN -t)

if [ -n "$PID" ]; then
    echo "找到监听 $PORT 的进程 PID: $PID，正在终止..."
    kill $PID
    echo "进程 $PID 已终止。"
else
    echo "未找到监听端口 $PORT 的进程。"
fi
sleep 3

nohup python startup.py --all-api 2>&1 &