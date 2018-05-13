function fixNavbarIssue(){

/*  Quick & dirt draft fix for the bootstrap's navbar-fixed-top issue.

Overview
  When you call a given section of a document (e.g. via <a href="#section"> or domain.com/page#section1) browsers show that section at the top of window. Bootstrap's navbar-fixed-top, _since it's fixed_, *overlays* first lines of content.
  This function catches all of the <a> tags pointing to a section of the page and rewrites them to properly display content.
  Works fine even if a # section is called from URL.

Usage
  Paste this function wherever you want in your document and append _fixNavbarIssue()_ to your <body>'s onload attribute.

Bugs:

  www.claudiodangelis.it
  claudiodangelis@gmail.com

*/
   
  if($(document).width()>768){  // Required if "viewport" content is "width=device-width, initial-scale=1.0": navbar is not fixed on lower widths.

    var hash = window.location.hash;

    // Code below fixes the issue if you land directly onto a page section (http://domain/page.html#section1)
    
    if(hash!=""){
      $(document).scrollTop(($(hash).offset().top) - $(".navbar-fixed-top").height());  
    }

    // This adds any <a> element 
    var locationHref = window.location.protocol + '//' + window.location.host + $(window.location).attr('pathname');
    var anchorsList = $('a').get();

    for(i=0;i<anchorsList.length;i++){
      var hash = anchorsList[i].href.replace(locationHref,'');
      if (hash[0] == "#" && hash != "#"){
        var originalOnClick = anchorsList[i].onclick; // Retain your pre-defined onClick functions
        setNewOnClick(originalOnClick,hash);
      }
    }
  }

  function setNewOnClick(originalOnClick,hash){
    anchorsList[i].onclick=function(){
      $(originalOnClick);
      $(document).scrollTop(($(hash).offset().top) - $(".navbar-fixed-top").height());
      return false;
    };
  }
}