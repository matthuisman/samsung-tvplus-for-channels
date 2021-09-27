# Samsung TV Plus for Channels

This simple Docker image will generate an M3U playlist and EPG optimized for use in [Channels](https://getchannels.com) and expose them over HTTP.

[Channels](https://getchannels.com) supports [custom channels](https://getchannels.com/docs/channels-dvr-server/how-to/custom-channels/) by utilizing streaming sources via M3U playlists.

[Channels](https://getchannels.com) allows for [additional extended metadata tags](https://getchannels.com/docs/channels-dvr-server/how-to/custom-channels/#channels-extensions) in M3U playlists that allow you to give it extra information and art to make the experience better. This project adds those extra tags to make things look great in Channels.

## Set Up

Running the container is easy. Fire up the container as usual. You can set which port it runs on.

    docker run -d --restart unless-stopped --name samsung-tvplus-for-channels -p 8182:80 matthuisman/samsung-tvplus-for-channels

By default, the service will retrieve data for `all` supported regions.  
If you want to use a specific region, you can manually set `REGION` environment variable to something like `us`.  
Valid regions can be found [here](https://i.mjh.nz/SamsungTVPlus/).

You can retrieve the playlist and EPG URLS via the status page.

    http://127.0.0.1:8182

## Add Source to Channels

Once you have your the container running, you can use it with [custom channels](https://getchannels.com/docs/channels-dvr-server/how-to/custom-channels/) in the [Channels](https://getchannels.com) app.

Add a new source in Channels DVR Server and choose `M3U Playlist`.  
Fill out the form using your new playlist and EPG URLs from above.

## License

MIT
