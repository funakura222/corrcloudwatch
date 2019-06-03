import datetime
import json
import os
import pickle
import sys

import pandas as pd
from flask import Flask, Response, render_template, request, url_for

import aws
import calc
import misc

app = Flask(__name__)


@app.route("/", methods=["GET", "POST"])
def index():

    if request.method == "GET":
        list_metrics = []
        base = os.path.dirname(os.path.abspath(__file__)).replace(os.sep, "/")
        filename = "all_metrics_file.pickle"
        all_metrics_file = base + "/static/tmp/" + filename
        if os.path.exists(all_metrics_file):
            with open(all_metrics_file, 'rb') as f:
                list_metrics = pickle.load(f)
                print("read metrics from pickle file.")
        else:
            list_metrics = aws.list_metrics()
            with open(all_metrics_file, 'wb') as f:
                pickle.dump(list_metrics, f)
                print("get metrics from aws.")

        return render_template(
            'index.html',
            list_metrics=list_metrics,
            list_metrics_count=len(list_metrics)
        )
    else:
        metricDataQueries = []

        query = {}
        period = int(request.form["period"])
        statistics = str(request.form["statistics"])
        start_datetime = datetime.datetime.strptime(
            request.form["start_datetime"], '%Y-%m-%d %H:%M'
        )
        end_datetime = datetime.datetime.strptime(
            request.form["end_datetime"], '%Y-%m-%d %H:%M'
        )
        tmp_metrics_label = request.form.getlist("target_metrics_label")
        tmp_metrics = request.form.getlist("target_metrics")

        for index in range(len(tmp_metrics)):
            namespace = tmp_metrics[index].split(",")[0]
            metricName = tmp_metrics[index].split(",")[1]
            if len(tmp_metrics[index].split(",")) == 3:
                name = tmp_metrics[index].split(",")[2].split("=")[0]
                value = tmp_metrics[index].split(",")[2].split("=")[1]

            if len(tmp_metrics[index].split(",")) == 3:
                metricDataQueries.append(
                    {
                        'Id': "m{}".format(index),
                        'Label': tmp_metrics_label[index],
                        'MetricStat': {
                            'Metric': {
                                'Namespace': namespace,
                                'MetricName': metricName,
                                'Dimensions': [
                                    {
                                        'Name': name,
                                        'Value': value
                                    },
                                ]
                            },
                            'Period': period,
                            'Stat': statistics,
                        }
                    },
                )

            else:
                metricDataQueries.append(
                    {
                        'Id': "m{}".format(index),
                        'Label': tmp_metrics_label[index],
                        'MetricStat': {
                            'Metric': {
                                'Namespace': namespace,
                                'MetricName': metricName,
                            },
                            'Period': period,
                            'Stat': statistics,
                        }
                    },
                )

        data = aws.get_metrics(
            metricDataQueries=metricDataQueries,
            start_time=start_datetime,
            end_time=end_datetime,
        )

        metrics_datas = []

        labelindex = []
        metrics_data_tmp = {}
        for item in data:
            if len(labelindex) < len(metricDataQueries):
                labelindex.append(
                    {
                        "Label": item["Label"],
                        "Metric": metricDataQueries[len(labelindex)]["MetricStat"]
                    }
                )
                metrics_data_tmp[item["Label"]] = []
            for index in range(len(item["Timestamps"])):
                metrics_data_tmp[item["Label"]].append(
                    {
                        "Timestamps": item["Timestamps"][index],
                        item["Label"]: item["Values"][index],
                    }
                )

        for key in metrics_data_tmp:
            metrics_data = pd.DataFrame(metrics_data_tmp[key])
            metrics_datas.append(metrics_data)

        merge_data = pd.DataFrame()
        try:
            for index in range(len(labelindex)):
                if index > 0:
                    merge_data = merge_data.merge(
                        metrics_datas[index],
                        how="inner",
                        on="Timestamps")
                else:
                    merge_data = metrics_datas[0]

            # Timestampsが先頭にない場合があるので、先頭にもってくる
            columns = merge_data.columns.tolist()
            columns.remove("Timestamps")
            columns.insert(0, "Timestamps")
            merge_data = merge_data.ix[:, columns]

            # 相関係数算出
            corr_data = calc.corr(merge_data)

            # 散布図行列を出力
            calc.pairplot(merge_data)

            # csvダウンロードの準備
            base = os.path.dirname(os.path.abspath(
                __file__)).replace(os.sep, "/")
            filename = "/static/tmp/result.csv"
            fullpath = base + filename
            merge_data.to_csv(fullpath)

        except:
            import traceback
            error = traceback.format_exc()
            return render_template(
                'corr_result.html',
                error=misc.str_to_html(error)
            )

        return render_template(
            'corr_result.html',
            result=corr_data.to_html(),
            src_data_start=merge_data[:5].to_html(),
            src_data_end=merge_data[-10:].to_html(),
            labelindex=labelindex
        )


@app.route('/download/<filename>', methods=["GET"])
def download_file(filename):
    """
    ファイルダウンロード
        :param filename: ダウンロードする/static/tmp内のファイル名
    """
    base = os.path.dirname(os.path.abspath(
        __file__)).replace(os.sep, "/")
    subfolder = "/static/tmp/"
    fullpath = base + subfolder + filename
    with open(fullpath, 'r') as f:
        file_contents = f.read()

    return Response(
        file_contents,
        mimetype="text/csv",
        headers={"Content-disposition":
                 "attachment; filename=" + filename})


@app.route('/getlistmetrics', methods=["GET"])
def get_list_metrics():
    """
    メトリクスを再取得します
    """
    base = os.path.dirname(os.path.abspath(
        __file__)).replace(os.sep, "/")
    subfolder = "/static/tmp/"
    filename = "all_metrics_file.pickle"
    fullpath = base + subfolder + filename

    if os.path.exists(fullpath):
        os.remove(fullpath)

    list_metrics = aws.list_metrics()
    with open(fullpath, 'wb') as f:
        pickle.dump(list_metrics, f)
    print("get metrics from aws.")

    content = """<label>再取得しました</label>
    <a class="nav-link" href="/">戻る</a>"""

    return Response(
        content,
        mimetype="text/html"
    )


@app.context_processor
def override_url_for():
    return dict(url_for=dated_url_for)


def dated_url_for(endpoint, **values):
    if endpoint == 'static':
        filename = values.get('filename', None)
        if filename:
            file_path = os.path.join(app.root_path,
                                     endpoint, filename)
            values['q'] = int(os.stat(file_path).st_mtime)
    return url_for(endpoint, **values)


if __name__ == '__main__':
    app.debug = True
    app.run(host='localhost', port=5000)
