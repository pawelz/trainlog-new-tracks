# trainlog-new-tracks

Generates a map of new tracks taken since date

# Dependencies

You will need the following libraries: polyline, shapely, pandas. Try:

```sh
$ pip install polyline shapely pandas
```

If that doesn't work, try:

```sh
$ pip3 install polyline shapely pandas
```

# How to use it

1. Export your data from trainlog, save it in a file `trainlog_export.csv`.
2. Run
   ```sh
   $ python3 trainlog_new_tracks.py --input_file trainlog_export.csv --since_day 2025-01-01
   ```
3. Create an account at https://dev.trainlog.me
4. Import the `new_rtacks.csv` file produced by the Python in that account.

Note that the data in dev.trainlog.me is ocasionally cleared, so don't rely on
any data stored there! Keep your csv file so that you can reupload it later.

*No robots were harmed during the making of this code.*