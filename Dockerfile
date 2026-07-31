FROM alpine:3.20
RUN apk add --no-cache python3
COPY sm_dsp_engine                  /opt/sm-dist/sm_dsp_engine
COPY docker-jellyfin/sm_wrapper.sh /opt/sm-dist/sm_wrapper.sh
COPY docker-jellyfin/setup.sh       /opt/sm-dist/setup.sh
COPY docker-jellyfin/entrypoint.sh  /opt/sm-dist/entrypoint.sh
COPY peq_toggle_nas.py              /opt/sm-dist/peq_toggle_nas.py
COPY engine_runtime.py              /opt/sm-dist/engine_runtime.py
COPY profile-proxy.py               /opt/sm-dist/profile-proxy.py
RUN chmod +x /opt/sm-dist/sm_dsp_engine /opt/sm-dist/sm_wrapper.sh /opt/sm-dist/setup.sh /opt/sm-dist/entrypoint.sh
ENTRYPOINT ["/opt/sm-dist/entrypoint.sh"]
CMD ["python3", "/opt/sm/peq_toggle_nas.py"]
