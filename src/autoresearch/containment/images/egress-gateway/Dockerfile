FROM python:3.13-alpine
COPY proxy.py /proxy.py
USER nobody
ENTRYPOINT ["python3", "-u", "/proxy.py"]
